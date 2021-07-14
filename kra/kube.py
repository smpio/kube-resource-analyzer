import kubernetes.client as api
from kubernetes.utils import parse_quantity

from kra.models import WorkloadKind

MEBIBYTE = 1024 * 1024


read_funcs = {
    WorkloadKind.ReplicaSet: api.AppsV1Api().read_namespaced_replica_set,
    WorkloadKind.Deployment: api.AppsV1Api().read_namespaced_deployment,
    WorkloadKind.DaemonSet: api.AppsV1Api().read_namespaced_daemon_set,
    WorkloadKind.CronJob: api.BatchV1beta1Api().read_namespaced_cron_job,
    WorkloadKind.StatefulSet: api.AppsV1Api().read_namespaced_stateful_set,
    WorkloadKind.Job: api.BatchV1Api().read_namespaced_job,
}

patch_funcs = {
    WorkloadKind.ReplicaSet: api.AppsV1Api().patch_namespaced_replica_set,
    WorkloadKind.Deployment: api.AppsV1Api().patch_namespaced_deployment,
    WorkloadKind.DaemonSet: api.AppsV1Api().patch_namespaced_daemon_set,
    WorkloadKind.CronJob: api.BatchV1beta1Api().patch_namespaced_cron_job,
    WorkloadKind.StatefulSet: api.AppsV1Api().patch_namespaced_stateful_set,
    WorkloadKind.Job: api.BatchV1Api().patch_namespaced_job,
}

containers_paths = {
    WorkloadKind.ReplicaSet: ['spec', 'template', 'spec', 'containers'],
    WorkloadKind.Deployment: ['spec', 'template', 'spec', 'containers'],
    WorkloadKind.DaemonSet: ['spec', 'template', 'spec', 'containers'],
    WorkloadKind.CronJob: ['spec', 'jobTemplate', 'spec', 'template', 'spec', 'containers'],
    WorkloadKind.StatefulSet: ['spec', 'template', 'spec', 'containers'],
    WorkloadKind.Job: ['spec', 'template', 'spec', 'containers'],
}


def get_workload_obj(workload):
    read_obj = read_funcs[workload.kind]
    return read_obj(workload.name, workload.namespace)


def get_workload_containers(workload):
    obj = get_workload_obj(workload)
    path = containers_paths[workload.kind]
    for part in path:
        obj = getattr(obj, _camel_case_to_snake_case(part))
    return obj


def get_container_resources(container):
    data = {}
    if container.resources:
        if container.resources.limits:
            data['memory_limit_mi'] = parse_memory_quantity(container.resources.limits.get('memory'))
        if container.resources.requests:
            data['cpu_request_m'] = parse_cpu_quantity(container.resources.requests.get('cpu'))
    return data


def parse_memory_quantity(q):
    if q is None:
        return None
    return parse_quantity(q) / MEBIBYTE


def parse_cpu_quantity(q):
    if q is None:
        return None
    return parse_quantity(q) * 1000


def _camel_case_to_snake_case(s: str):
    def conv(c: str):
        if c.isupper():
            return '_' + c.lower()
        return c

    return ''.join(conv(c) for c in s)
