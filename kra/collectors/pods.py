import queue
import logging
import time

import kubernetes
import kubernetes.client.rest
from django.db import transaction
from django.utils import timezone

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import retry_on_connection_close
from utils.django.db import fix_long_connections

from kra import kube
from kra import models
from kra.oom import record_oom_termination

log = logging.getLogger(__name__)


def main():
    install_shutdown_signal_handlers()

    q = queue.Queue()
    threads = SupervisedThreadGroup()
    threads.add_thread(WatcherThread(q))
    threads.add_thread(HandlerThread(q))
    threads.add_thread(GitOpsReconciliationThread())
    threads.start_all()
    threads.wait_any()


class GitOpsReconciliationThread(SupervisedThread):
    def run_supervised(self):
        from kra.tasks import reconcile_gitops_adjustments

        while True:
            try:
                fix_long_connections()
                reconcile_gitops_adjustments.apply_async(expires=60)
            except Exception:
                log.exception('Failed to queue GitOps reconciliation')
            time.sleep(30)


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
    resources = {
        container.name: {'name': container.name, **kube.get_container_resources(container)}
        for container in pod.spec.containers
    }
    for status in pod.status.container_statuses or []:
        data = resources[status.name]
        runtime_id = kube.parse_container_runtime_id(status.container_id)
        if status.state and status.state.running and runtime_id:
            update_container(mypod, runtime_id, {
                **data, 'started_at': status.state.running.started_at, 'finished_at': None,
            })

        # In CrashLoopBackOff there may be no current runtime ID at all.
        # last_state still identifies the exact previous container execution.
        for state in (status.state, status.last_state):
            terminated = state.terminated if state is not None else None
            if terminated is None:
                continue
            terminated_id = kube.parse_container_runtime_id(terminated.container_id)
            if terminated_id is None and state is status.state:
                terminated_id = runtime_id
            if terminated_id is None or terminated.started_at is None:
                log.info('Incomplete termination identity for container %s in pod %s/%s',
                         status.name, pod.metadata.namespace, pod.metadata.name)
                continue
            update_container(mypod, terminated_id, {
                **data, 'started_at': terminated.started_at, 'finished_at': terminated.finished_at,
            }, terminated=terminated, historical=state is status.last_state)


def update_container(pod, runtime_id, data, terminated=None, historical=False):
    if historical:
        # Current pod resources say nothing about a previous execution's limit.
        # Preserve observed historical values; leave unobserved limits unknown.
        data = {key: value for key, value in data.items()
                if key not in ('memory_limit_mi', 'cpu_request_m')}
    with transaction.atomic():
        # update_or_create holds the same row lock as the OOM handler.
        container, _ = models.Container.objects.update_or_create(
            pod=pod, runtime_id=runtime_id, defaults=data,
        )
        if terminated is not None:
            record_oom_termination(container, terminated)


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
    workload_kind = models.WorkloadKind.__members__.get(kind)
    if workload_kind is None:
        # Custom controllers (e.g. CloudNativePG Cluster) are not workload kinds
        # supported by recommendations. Keep collecting their pods and metrics.
        return lambda name, ns: None
    return kube.read_funcs[workload_kind]


def get_pod_spec_hash(pod):
    return pod.metadata.labels.get('controller-revision-hash') or pod.metadata.labels.get('pod-template-hash') or ''


if __name__ == '__main__':
    main()
