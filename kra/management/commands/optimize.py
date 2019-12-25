import logging

from django.core.management.base import BaseCommand

from kra import models

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Analyze and optimize'

    def add_arguments(self, parser):
        parser.add_argument('--force-update', action='store_true', help='Force analytics update')

    def handle(self, *args, **options):
        for sug in models.Suggestion.get_all(options['force_update']):
            print(f'{sug.workload.kind.name} {sug.workload.namespace}/{sug.workload.name}'
                  f' (container {sug.container_name})')

            if sug.new_memory_limit_mi:
                print(f'  new memory limit: {sug.new_memory_limit_mi} Mi')

            if sug.new_cpu_request_m:
                print(f'  new CPU request: {sug.new_cpu_request_m}m')

            print(f'  priority: {sug.priority}')
            print('  ' + sug.reason)
