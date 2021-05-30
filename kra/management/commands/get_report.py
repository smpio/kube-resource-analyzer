from collections import defaultdict

from django.db.models import F
from django.core.management.base import BaseCommand

from kra import models, tasks


class Command(BaseCommand):
    help = 'Analyze and get report'

    def add_arguments(self, parser):
        parser.add_argument('--update', action='store_true', help='Update summaries')

    def handle(self, *args, **options):
        if options['update']:
            tasks.make_summaries()

        oom_events = defaultdict(list)
        oom_qs = models.OOMEvent.objects.all()\
            .prefetch_related('container')\
            .annotate(workload_id=F('container__pod__workload'))\
            .order_by('happened_at')
        for e in oom_qs:
            oom_events[(e.workload_id, e.container.name)].append(e)

        qs = models.Summary.objects\
                .order_by('workload__namespace', 'workload__name')\
                .select_related('workload')
        for stat in qs:
            print(f'{stat.workload.kind.name} {stat.workload.namespace}/{stat.workload.name}'
                  f' (container {stat.container_name})')

            if stat.avg_memory_mi:
                stddev_memory_percent = round(stat.stddev_memory_mi / stat.avg_memory_mi * 100)
            else:
                stddev_memory_percent = 0
            print(f'  {stat.max_memory_mi} Mi', end='')
            if stat.memory_limit_mi:
                print(f' / {stat.memory_limit_mi} Mi', end='')
            print(f', avg: {stat.avg_memory_mi} Mi', end='')
            print(f', stdDev: {stat.stddev_memory_mi} Mi', end='')
            print(f' ({stddev_memory_percent}%)', end='')
            print()

            if stat.avg_cpu_m:
                stddev_cpu_percent = round(stat.stddev_cpu_m / stat.avg_cpu_m * 100)
            else:
                stddev_cpu_percent = 0
            print(f'  {stat.max_cpu_m}m', end='')
            if stat.cpu_request_m:
                print(f' / {stat.cpu_request_m}m', end='')
            print(f', avg: {stat.avg_cpu_m}m', end='')
            print(f', stdDev: {stat.stddev_cpu_m}m', end='')
            print(f' ({stddev_cpu_percent}%)', end='')
            print()

            for oom in oom_events[(stat.workload.id, stat.container_name)]:
                msg = f'  OOM {oom.happened_at}'
                if oom.target_pid:
                    msg += f' target:{oom.target_comm}({oom.target_pid})'
                if oom.victim_pid:
                    msg += f' victim:{oom.victim_comm}({oom.victim_pid})'
                if oom.container.memory_limit_mi:
                    msg += f' limit:{oom.container.memory_limit_mi} Mi'
                print(msg)
