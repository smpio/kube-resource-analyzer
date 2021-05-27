import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Max

from utils.django.db import bulk_save

from kra import models

log = logging.getLogger(__name__)


@transaction.atomic
def make_summary():
    models.Summary.objects.all().delete()

    resource_usage = defaultdict(lambda: defaultdict(list))
    resource_usage_qs = models.ResourceUsage.objects\
        .values('container__pod_id', 'container__name')\
        .annotate(
            max_memory_mi=Max('memory_mi'),
            last_cpu_m_seconds=Max('cpu_m_seconds'),
            last_measured_at=Max('measured_at'),
        )
    pod_ids = (ru['container__pod_id'] for ru in resource_usage_qs)
    pods = models.Pod.objects.filter(id__in=pod_ids).in_bulk(field_name='id')

    for ru in resource_usage_qs:
        pod = pods[ru['container__pod_id']]
        ru['container__pod'] = pod
        resource_usage[pod.workload_id][ru['container__name']].append(ru)

    with bulk_save() as save:
        for wl in models.Workload.objects.order_by('namespace', 'name'):
            try:
                workload_ru = resource_usage[wl.id]
            except KeyError:
                continue

            for container_name, container_ru in workload_ru.items():
                if not container_ru:
                    continue

                summary = models.Summary(workload=wl, container_name=container_name)
                save(summary)
                for instance_summary in _fill_summary(summary, container_ru):
                    save(instance_summary)
                yield summary


def _fill_summary(summary, rus):
    rus.sort(key=lambda ru: ru['container__pod'].started_at)
    last_container = models.Container.objects.get(pod=rus[-1]['container__pod'], name=summary.container_name)
    summary.memory_limit_mi = last_container.memory_limit_mi
    summary.cpu_request_m = last_container.cpu_request_m

    summary.max_memory_mi = 0
    total_running_seconds = 0
    total_cpu_m_seconds = 0

    for ru in rus:
        instance_summary = models.InstanceSummary(aggregated=summary)

        instance_summary.max_memory_mi = ru['max_memory_mi']
        summary.max_memory_mi = max(summary.max_memory_mi, instance_summary.max_memory_mi)

        running_seconds = (ru['last_measured_at'] - ru['container__pod'].started_at).total_seconds()
        instance_summary.avg_cpu_m = round(ru['last_cpu_m_seconds'] / running_seconds)
        total_running_seconds += running_seconds
        total_cpu_m_seconds += ru['last_cpu_m_seconds']

        yield instance_summary

    summary.avg_cpu_m = round(total_cpu_m_seconds / total_running_seconds)
