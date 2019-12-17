import queue
import logging
import threading

import kubernetes
import kubernetes.client.rest
from kubernetes.utils import parse_quantity
from django.utils import timezone

from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers

from kra import models, kube_config

log = logging.getLogger(__name__)


def main():
    install_shutdown_signal_handlers()
    kube_config.init()

    q = queue.Queue()
    handler = HandlerThread(q)
    handler.start()

    v1 = kubernetes.client.CoreV1Api()

    for event_type, pod in KubeWatcher(v1.list_pod_for_all_namespaces):
        q.put((event_type, pod))


class HandlerThread(threading.Thread):
    def __init__(self, queue):
        super().__init__(daemon=True)
        self.queue = queue
        self.initial_pods = set()
        self.handle = self.handle_initial_event

    def run(self):
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
        'spec_hash': '?',  # TODO
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
    for container in pod.spec.containers:
        container_data = {}
        if container.resources:
            if container.resources.limits:
                container_data['memory_limit_mi'] = parse_memory_quantity(container.resources.limits.get('memory'))
            if container.resources.requests:
                container_data['cpu_request_m'] = parse_cpu_quantity(container.resources.requests.get('cpu'))
        models.Container.objects.update_or_create(pod=mypod, name=container.name, defaults=container_data)


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
    else:
        raise Exception('Unknown controller kind: %s', kind)


def parse_memory_quantity(q):
    if q is None:
        return None
    return parse_quantity(q) / 1024 / 1024


def parse_cpu_quantity(q):
    if q is None:
        return None
    return parse_quantity(q) * 1000


if __name__ == '__main__':
    main()
