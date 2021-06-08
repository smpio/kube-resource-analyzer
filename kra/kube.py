import kubernetes.client as api

from kra.models import WorkloadKind


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
