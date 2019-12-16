import logging

import kubernetes
import kubernetes.client.rest
from django.utils import timezone

from kra import models
from kra import kube_watch

log = logging.getLogger(__name__)


def main():
    configuration = kubernetes.client.Configuration()
    configuration.host = 'http://127.0.0.1:8001'
    kubernetes.client.Configuration.set_default(configuration)

    # TODO: get initial pods on startup and mark others as gone

    # TODO: add events to queue and handle them in separate thread
    #       (and handle errors: pod already deleted, workload deleted, etc)
    #       log events in queue

    v1 = kubernetes.client.CoreV1Api()

    for event_type, pod in kube_watch.watch(v1.list_pod_for_all_namespaces):
        log.info('%s %s/%s', event_type.name, pod.metadata.namespace, pod.metadata.name)

        if event_type in (kube_watch.EventType.ADDED, kube_watch.EventType.MODIFIED):
            handle_update(pod)
        elif event_type == kube_watch.EventType.DELETED:
            handle_delete(pod)


def handle_delete(pod):
    models.Pod.objects.filter(uid=pod.metadata.uid).update(gone_at=timezone.now())


def handle_update(pod):
    if pod.status.start_time is None:
        # Pod is creating, and not started yet
        return

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
                log.warning('Failed to get workload for pod %s/%s: Not Found',
                            pod.metadata.namespace, pod.metadata.name)
            else:
                raise e
    except Exception:
        log.warning('Failed to get workload for pod %s/%s',
                    pod.metadata.namespace, pod.metadata.name, exc_info=True)

    models.Pod.objects.update_or_create(uid=pod.metadata.uid, defaults=data)


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


if __name__ == '__main__':
    main()
