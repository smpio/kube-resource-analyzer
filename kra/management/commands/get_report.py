import logging

from django.db.models import Max, Avg
from django.core.management.base import BaseCommand

from kra import models

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Analyze and get report'

    def handle(self, *args, **options):
        for wl in models.Workload.objects.order_by('namespace', 'name'):
            resource_usage_qs = models.ResourceUsage.objects.filter(container__pod__workload=wl)

            stat = Struct(resource_usage_qs.aggregate(max_memory_mi=Max('memory_mi'), avg_cpu_m=Avg('cpu_m')))
            if stat.avg_cpu_m is not None:
                stat.avg_cpu_m = int(stat.avg_cpu_m)

            print(f'{wl.kind.name} {wl.namespace}/{wl.name}')
            if stat.max_memory_mi is not None:
                print(f'\tmax memory: {stat.max_memory_mi} Mi')
            if stat.avg_cpu_m is not None:
                print(f'\tavg CPU: {stat.avg_cpu_m}m')


class Struct:
    def __init__(self, entries):
        self.__dict__.update(entries)
