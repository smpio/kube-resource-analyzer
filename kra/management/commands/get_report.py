import logging

from django.core.management.base import BaseCommand

from kra import models

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Analyze and get report'

    def handle(self, *args, **options):
        for stat in models.Investigation.get_all():
            print(f'{stat.workload.kind.name} {stat.workload.namespace}/{stat.workload.name}'
                  f' (container {stat.container_name})')

            if stat.max_memory_mi is not None:
                msg = f'  max memory: {stat.max_memory_mi} Mi'
                if stat.memory_limit_mi:
                    msg += f' / {stat.memory_limit_mi} Mi'
                print(msg)

            if stat.avg_cpu_m is not None:
                msg = f'  avg CPU: {stat.avg_cpu_m}m'
                if stat.cpu_request_m:
                    msg += f' / {stat.cpu_request_m}m'
                print(msg)
