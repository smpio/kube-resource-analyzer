import logging

from django.db import transaction
from django.db.models import Max, Avg

from kra import models

log = logging.getLogger(__name__)


@transaction.atomic
def make_investigations():
    models.Investigation.objects.all().delete()

    for wl in models.Workload.objects.order_by('namespace', 'name'):
        resource_usage_qs = models.ResourceUsage.objects\
            .filter(container__pod__workload=wl)\
            .values('container__name')\
            .annotate(max_memory_mi=Max('memory_mi'), avg_cpu_m=Avg('cpu_m'))

        for cu in resource_usage_qs:
            stat = models.Investigation(workload=wl, container_name=cu['container__name'])
            stat.max_memory_mi = cu['max_memory_mi']
            if cu['avg_cpu_m'] is not None:
                stat.avg_cpu_m = int(cu['avg_cpu_m'])

            last_container = models.Container.objects\
                .filter(pod__workload=wl, name=stat.container_name)\
                .order_by('pod__started_at')\
                .last()

            if last_container is not None:
                stat.memory_limit_mi = last_container.memory_limit_mi
                stat.cpu_request_m = last_container.cpu_request_m

            stat.save()
            yield stat
