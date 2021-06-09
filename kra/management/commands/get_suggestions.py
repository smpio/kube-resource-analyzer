from django.core.management.base import BaseCommand

from kra import models, tasks


class Command(BaseCommand):
    help = 'Analyze and get suggestions'

    def add_arguments(self, parser):
        parser.add_argument('--update', action='store_true', help='Update suggestions')
        parser.add_argument('--update-all', action='store_true', help='Also update summaries')

    def handle(self, *args, **options):
        if options['update_all']:
            tasks.make_summaries()
        if options['update_all'] or options['update']:
            tasks.make_suggestions()

        for sug in models.Suggestion.objects.order_by('-priority').select_related('summary__workload'):
            stat = sug.summary
            workload = stat.workload

            print(f'{workload.kind.name} {workload.namespace}/{workload.name}'
                  f' (container {stat.container_name})')

            if sug.new_memory_limit_mi is not None:
                print(f'  set memory limit to {sug.new_memory_limit_mi} Mi', end='')
                if stat.memory_limit_mi is not None:
                    print(f' (current: {stat.memory_limit_mi} Mi)')
                else:
                    print(' (current: not set)')
                if sug.memory_reason:
                    print('    ' + sug.memory_reason)

            if sug.new_cpu_request_m is not None:
                print(f'  set CPU request to {sug.new_cpu_request_m}m', end='')
                if stat.cpu_request_m is not None:
                    print(f' (current: {stat.cpu_request_m}m)')
                else:
                    print(' (current: not set)')
                if sug.cpu_reason:
                    print('    ' + sug.cpu_reason)

            print(f'  priority: {sug.priority}')
