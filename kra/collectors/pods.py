import re
import queue
import logging

import kubernetes
import kubernetes.client.rest
from kubernetes.utils import parse_quantity
from django.utils import timezone

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import retry_on_connection_close

from kra import models, kube_config

log = logging.getLogger(__name__)
container_runtime_id_re = re.compile(r'^\w+://(.+)$')

MEBIBYTE = 1024 * 1024


def main():
    install_shutdown_signal_handlers()
    kube_config.init()

    q = queue.Queue()
    threads = SupervisedThreadGroup()
    threads.add_thread(WatcherThread(q))
    threads.add_thread(HandlerThread(q))
    threads.start_all()
    threads.wait_any()


class WatcherThread(SupervisedThread):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def run_supervised(self):
        v1 = kubernetes.client.CoreV1Api()
        for event_type, pod in KubeWatcher(v1.list_pod_for_all_namespaces):
            self.queue.put((event_type, pod))


class HandlerThread(SupervisedThread):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self.initial_pods = set()
        self.handle = self.handle_initial_event

    def run_supervised(self):
        while True:
            event_type, pod = self.queue.get()
            try:
                self.handle(event_type, pod)
            except Exception:
                log.exception('Failed to handle %s on pod %s/%s',
                              event_type.name, pod.metadata.namespace, pod.metadata.name)

    def handle_initial_event(self, event_type, pod):
        if event_type == WatchEventType.ADDED:
            self.initial_pods.add(pod.metadata.uid)

        if event_type == WatchEventType.DONE_INITIAL:
            self.handle = self.handle_normal_event
            self.initial_cleanup()
        else:
            self.handle_normal_event(event_type, pod)

    @retry_on_connection_close()
    def handle_normal_event(self, event_type, pod):
        log.info('%s %s/%s', event_type.name, pod.metadata.namespace, pod.metadata.name)

        if event_type in (WatchEventType.ADDED, WatchEventType.MODIFIED):
            self.handle_update(pod)
        elif event_type == WatchEventType.DELETED:
            self.handle_delete(pod)

    def handle_delete(self, pod):
        models.Pod.objects.filter(uid=pod.metadata.uid).update(gone_at=timezone.now())

    def handle_update(self, pod):
        if pod.status.start_time is None:
            # Pod is creating, and not started yet
            return
        update_pod(pod)

    def initial_cleanup(self):
        qs = models.Pod.objects.filter(gone_at=None).exclude(uid__in=self.initial_pods)
        count = qs.update(gone_at=timezone.now())
        log.info('Marked %d pods as gone', count)
        del self.initial_pods


def update_pod(pod):
    data = {
        'namespace': pod.metadata.namespace,
        'name': pod.metadata.name,
        'spec_hash': get_pod_spec_hash(pod),
        'started_at': pod.status.start_time,
    }

    try:
        try:
            data['workload'] = get_workload_from_pod(pod)
        except kubernetes.client.rest.ApiException as e:
            if e.status == 404:
                log.info('Failed to get workload for pod %s/%s: Not Found',
                         pod.metadata.namespace, pod.metadata.name)
            else:
                raise e
    except Exception:
        log.warning('Failed to get workload for pod %s/%s',
                    pod.metadata.namespace, pod.metadata.name, exc_info=True)

    mypod, _ = models.Pod.objects.update_or_create(uid=pod.metadata.uid, defaults=data)
    update_containers(pod, mypod)


def update_containers(pod, mypod):
    mycontainers = {}

    for container in pod.spec.containers:
        data = {}
        if container.resources:
            if container.resources.limits:
                data['memory_limit_mi'] = parse_memory_quantity(container.resources.limits.get('memory'))
            if container.resources.requests:
                data['cpu_request_m'] = parse_cpu_quantity(container.resources.requests.get('cpu'))

        mycontainers[container.name] = data

    for container_status in pod.status.container_statuses:
        if container_status.state.running:
            mycontainers[container_status.name]['started_at'] = container_status.state.running.started_at
        elif container_status.state.terminated:
            mycontainers[container_status.name]['started_at'] = container_status.state.terminated.started_at

        if not container_status.container_id:
            # container is terminating
            continue
        runtime_id = parse_container_runtime_id(container_status.container_id)
        mycontainers[container_status.name]['runtime_id'] = runtime_id

    for name, data in mycontainers.items():
        if not data.get('runtime_id'):
            log.info(f'No runtime id for container {name} in pod {pod.metadata.namespace}/{pod.metadata.name}')
            continue

        models.Container.objects.update_or_create(pod=mypod, name=name, defaults=data)


def get_workload_from_pod(pod):
    owner = get_owner_recursive(pod)
    if owner is None:
        return None
    kind = models.WorkloadKind[owner.kind]
    wl, _ = models.Workload.objects.get_or_create(
        kind=kind,
        namespace=pod.metadata.namespace,
        name=owner.metadata.name
    )
    return wl


def get_owner_recursive(obj):
    if not obj.metadata.owner_references:
        return None

    for ref in obj.metadata.owner_references:
        if not ref.controller:
            continue

        read_func = kind_to_read_func(ref.kind)
        owner = read_func(name=ref.name, namespace=obj.metadata.namespace)
        if owner is None:
            return None

        superowner = get_owner_recursive(owner)
        if superowner is not None:
            return superowner

        return owner

    return None


def kind_to_read_func(kind):
    if kind == 'ReplicaSet':
        return kubernetes.client.AppsV1Api().read_namespaced_replica_set
    elif kind == 'Deployment':
        return kubernetes.client.AppsV1Api().read_namespaced_deployment
    elif kind == 'DaemonSet':
        return kubernetes.client.AppsV1Api().read_namespaced_daemon_set
    elif kind == 'CronJob':
        return kubernetes.client.BatchV1beta1Api().read_namespaced_cron_job
    elif kind == 'StatefulSet':
        return kubernetes.client.AppsV1Api().read_namespaced_stateful_set
    elif kind == 'Job':
        return kubernetes.client.BatchV1Api().read_namespaced_job
    elif kind == 'Node':
        return lambda name, ns: None
    else:
        raise Exception('Unknown controller kind: %s', kind)


def parse_memory_quantity(q):
    if q is None:
        return None
    return parse_quantity(q) / MEBIBYTE


def parse_cpu_quantity(q):
    if q is None:
        return None
    return parse_quantity(q) * 1000


def parse_container_runtime_id(container_id):
    match = container_runtime_id_re.match(container_id)
    if match is None:
        return None
    return match.group(1)


def get_pod_spec_hash(pod):
    return pod.metadata.labels.get('controller-revision-hash') or pod.metadata.labels.get('pod-template-hash') or ''


if __name__ == '__main__':
    main()
