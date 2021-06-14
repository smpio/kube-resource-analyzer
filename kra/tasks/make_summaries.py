import os
import pickle
import logging
from collections import defaultdict

from utils.django.db import bulk_save

from kra import models
from kra.analytics.container import get_containers_summary

log = logging.getLogger(__name__)


def make_summaries():
    containers_by_pod_id = None

    summary_dump_filename = os.environ.get('KRA_INTERMEDIATE_DUMP')
    if summary_dump_filename:
        try:
            with open(summary_dump_filename, 'rb') as summary_dump_file:
                containers_by_pod_id = pickle.load(summary_dump_file)
        except Exception:
            log.exception('Failed to load summary dump')

    if containers_by_pod_id is None:
        log.info('Query containers summary...')
        containers_by_pod_id = defaultdict(list)
        for c in get_containers_summary():
            containers_by_pod_id[c.pod_id].append(c)
        if summary_dump_filename:
            with open(summary_dump_filename, 'wb') as summary_dump_file:
                pickle.dump(containers_by_pod_id, summary_dump_file)

    log.info('Collecting results')

    pods_by_workload_id = defaultdict(list)
    for pod in models.Pod.objects.all():
        pods_by_workload_id[pod.workload_id].append(pod)

    models.Summary.objects.all().delete()

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


def make_summary(workload_id):
    log.info('Making summary for workload %s', workload_id)
    container_ids = models.Container.objects.filter(pod__workload_id=workload_id).values_list('id', flat=True)
    containers_by_name = defaultdict(list)
    for c in get_containers_summary(list(container_ids)):
        containers_by_name[c.name].append(c)

    models.Summary.objects.filter(workload_id=workload_id).delete()

    with bulk_save() as save:
        for container_name, containers in containers_by_name.items():
            summary = models.Summary(workload_id=workload_id, container_name=container_name)
            save(summary)
            for instance_summary in _fill_summary(summary, containers):
                save(instance_summary)


def _fill_summary(summary, containers):
    # containers arg does not contain containers without measurements
    last_container = models.Container.objects\
        .filter(pod__workload=summary.workload, name=summary.container_name)\
        .order_by('-started_at')\
        .first()

    summary.memory_limit_mi = last_container.memory_limit_mi
    summary.cpu_request_m = last_container.cpu_request_m

    summary.max_memory_mi = 0
    summary.max_cpu_m = 0

    total_seconds = 0
    total_cpu_m_seconds = 0
    total_memory_mi_seconds = 0
    total_stddev_cpu_m_seconds = 0
    total_stddev_memory_mi_seconds = 0

    for c in containers:
        instance_summary = models.InstanceSummary(aggregated=summary)

        instance_summary.max_memory_mi = c.max_memory_mi
        instance_summary.avg_memory_mi = c.avg_memory_mi
        instance_summary.stddev_memory_mi = c.stddev_memory_mi
        instance_summary.max_cpu_m = c.max_cpu_m
        instance_summary.avg_cpu_m = c.avg_cpu_m
        instance_summary.stddev_cpu_m = c.stddev_cpu_m

        summary.max_memory_mi = max(summary.max_memory_mi, c.max_memory_mi)
        summary.max_cpu_m = max(summary.max_cpu_m, c.max_cpu_m)

        total_seconds += c.total_seconds
        total_cpu_m_seconds += c.total_cpu_m_seconds
        total_memory_mi_seconds += c.total_memory_mi_seconds

        total_stddev_cpu_m_seconds += c.stddev_cpu_m * c.total_seconds
        total_stddev_memory_mi_seconds += c.stddev_memory_mi * c.total_seconds

        yield instance_summary

    summary.avg_cpu_m = round(total_cpu_m_seconds / total_seconds)
    summary.avg_memory_mi = round(total_memory_mi_seconds / total_seconds)
    summary.stddev_cpu_m = round(total_stddev_cpu_m_seconds / total_seconds)
    summary.stddev_memory_mi = round(total_stddev_memory_mi_seconds / total_seconds)
