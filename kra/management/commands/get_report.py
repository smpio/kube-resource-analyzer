import logging

from django.db.models import Max, Avg
from django.core.management.base import BaseCommand

from kra import models

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Analyze and get report'

    def handle(self, *args, **options):
        for wl in models.Workload.objects.order_by('namespace', 'name'):
            print(f'{wl.kind.name} {wl.namespace}/{wl.name}')

            resource_usage_qs = models.ResourceUsage.objects\
                .filter(container__pod__workload=wl)\
                .values('container__name')\
                .annotate(max_memory_mi=Max('memory_mi'), avg_cpu_m=Avg('cpu_m'))

            for container_resource_usage in resource_usage_qs:
                stat = Struct(container_resource_usage)

                last_container = models.Container.objects\
                    .filter(pod__workload=wl, name=stat.container__name)\
                    .order_by('pod__started_at')\
                    .last()

                print(f'  {stat.container__name}')

                if stat.avg_cpu_m is not None:
                    stat.avg_cpu_m = int(stat.avg_cpu_m)

                if stat.max_memory_mi is not None:
                    msg = f'    max memory: {stat.max_memory_mi} Mi'
                    if last_container and last_container.memory_limit_mi:
                        msg += f' / {last_container.memory_limit_mi} Mi'
                    print(msg)

                if stat.avg_cpu_m is not None:
                    msg = f'    avg CPU: {stat.avg_cpu_m}m'
                    if last_container and last_container.cpu_request_m:
                        msg += f' / {last_container.cpu_request_m}m'
                    print(msg)


class Struct:
    def __init__(self, entries):
        self.__dict__.update(entries)
