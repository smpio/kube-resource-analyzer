import queue
import logging

import kubernetes
import kubernetes.client.rest
from django.db import IntegrityError
from django.utils import timezone

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import retry_on_connection_close

from kra import kube
from kra import models

log = logging.getLogger(__name__)


def main():
    install_shutdown_signal_handlers()

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
        now = timezone.now()
        models.Pod.objects.filter(uid=pod.metadata.uid, gone_at=None).update(gone_at=now)
        models.Container.objects.filter(pod__uid=pod.metadata.uid, finished_at=None).update(finished_at=now)

    def handle_update(self, pod):
        if pod.status.start_time is None:
            # Pod is creating, and not started yet
            return
        update_pod(pod)

    def initial_cleanup(self):
        now = timezone.now()
        pod_qs = models.Pod.objects.filter(gone_at=None).exclude(uid__in=self.initial_pods)
        count = pod_qs.update(gone_at=now)
        log.info('Marked %d pods as gone', count)
        container_qs = models.Container.objects.filter(finished_at=None).exclude(pod__uid__in=self.initial_pods)
        count = container_qs.update(finished_at=now)
        log.info('Marked %d containers as finished', count)
        del self.initial_pods


def update_pod(pod):
    data = {
        'namespace': pod.metadata.namespace,
        'name': pod.metadata.name,
        'spec_hash': get_pod_spec_hash(pod),
        'started_at': pod.status.start_time,
        'gone_at': None,
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
        data = kube.get_container_resources(container)
        data['name'] = container.name
        mycontainers[container.name] = data

    for container_status in pod.status.container_statuses or []:
        runtime_id = None
        started_at = None
        finished_at = None

        if container_status.state.running:
            started_at = container_status.state.running.started_at
        elif container_status.state.terminated:
            started_at = container_status.state.terminated.started_at
            finished_at = container_status.state.terminated.finished_at
            runtime_id = kube.parse_container_runtime_id(container_status.state.terminated.container_id)

        runtime_id = kube.parse_container_runtime_id(container_status.container_id) or runtime_id
        mycontainers[container_status.name]['runtime_id'] = runtime_id
        mycontainers[container_status.name]['started_at'] = started_at
        mycontainers[container_status.name]['finished_at'] = finished_at

    for name, data in mycontainers.items():
        runtime_id = data.pop('runtime_id', None)
        if not runtime_id:
            log.info('No runtime_id for container %s in pod %s/%s', name, pod.metadata.namespace, pod.metadata.name)
            continue
        if not data.get('started_at'):
            log.info('No started_at for container %s in pod %s/%s', name, pod.metadata.namespace, pod.metadata.name)

        try:
            c, _ = models.Container.objects.update_or_create(pod=mypod, runtime_id=runtime_id, defaults=data)
        except IntegrityError as err:
            if data.get('started_at'):
                raise err


def get_workload_from_pod(pod):
    owner = get_owner_recursive(pod)
    if owner is None:
        return None
    kind = models.WorkloadKind[owner.kind]

    if kind == models.WorkloadKind.DaemonSet:
        affinity = None
    else:
        affinity = get_affinity_from_pod(pod)

    wl, _ = models.Workload.objects.update_or_create(
        kind=kind,
        namespace=pod.metadata.namespace,
        name=owner.metadata.name,
        defaults={
            'affinity': affinity,
        }
    )
    return wl


def get_affinity_from_pod(pod):
    if pod.spec.affinity:
        affinity = pod.spec.affinity.to_dict()
    else:
        affinity = {}

    if pod.spec.node_selector:
        affinity['node_selector'] = pod.spec.node_selector

    return affinity or None


def get_owner_recursive(obj):
    if not obj.metadata.owner_references:
        return None

    for ref in obj.metadata.owner_references:
        if not ref.controller:
            continue

        read_func = kind_to_read_func(ref.kind)
        owner = read_func(ref.name, obj.metadata.namespace)
        if owner is None:
            return None

        superowner = get_owner_recursive(owner)
        if superowner is not None:
            return superowner

        return owner

    return None


def kind_to_read_func(kind):
    if kind == 'Node':
        return lambda name, ns: None
    return kube.read_funcs[models.WorkloadKind[kind]]


def get_pod_spec_hash(pod):
    return pod.metadata.labels.get('controller-revision-hash') or pod.metadata.labels.get('pod-template-hash') or ''


if __name__ == '__main__':
    main()
