import logging
from collections import defaultdict

from django.db import transaction

from utils.django.db import bulk_save

from kra import models
from kra.analytics.container import get_containers_summary

log = logging.getLogger(__name__)


@transaction.atomic
def make_summary():
    models.Summary.objects.all().delete()

    log.info('Query containers summary...')
    containers_by_pod_id = defaultdict(list)
    for c in get_containers_summary():
        containers_by_pod_id[c.pod_id].append(c)
    log.info('DONE')

    log.info('Collecting results')

    pods_by_workload_id = defaultdict(list)
    for pod in models.Pod.objects.order_by('started_at'):
        pods_by_workload_id[pod.workload_id].append(pod)

    with bulk_save() as save:
        for wl in models.Workload.objects.all().order_by('namespace', 'name'):
            containers_by_name = defaultdict(list)
            for pod in pods_by_workload_id[wl.id]:
                for c in containers_by_pod_id[pod.id]:
                    containers_by_name[c.name].append(c)
            for container_name, containers in containers_by_name.items():
                summary = models.Summary(workload=wl, container_name=container_name)
                save(summary)
                for instance_summary in _fill_summary(summary, containers):
                    save(instance_summary)
                yield summary


def _fill_summary(summary, containers):
    last_container = containers[-1]
    summary.memory_limit_mi = last_container.memory_limit_mi
    summary.cpu_request_m = last_container.cpu_request_m

    summary.max_memory_mi = 0
    total_seconds = 0
    total_cpu_m_seconds = 0

    for c in containers:
        instance_summary = models.InstanceSummary(aggregated=summary)

        instance_summary.max_memory_mi = c.max_memory_mi
        instance_summary.avg_cpu_m = c.avg_cpu_m

        summary.max_memory_mi = max(summary.max_memory_mi, c.max_memory_mi)

        total_seconds += c.total_seconds
        total_cpu_m_seconds += c.total_cpu_m_seconds

        yield instance_summary

    summary.avg_cpu_m = round(total_cpu_m_seconds / total_seconds)
