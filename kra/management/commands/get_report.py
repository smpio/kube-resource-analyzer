from collections import defaultdict

from django.db.models import F
from django.core.management.base import BaseCommand

from kra import models


class Command(BaseCommand):
    help = 'Analyze and get report'

    def add_arguments(self, parser):
        parser.add_argument('--force-update', action='store_true', help='Force analytics update')

    def handle(self, *args, **options):
        oom_events = defaultdict(list)
        oom_qs = models.OOMEvent.objects.all()\
            .prefetch_related('container')\
            .annotate(workload_id=F('container__pod__workload'))\
            .order_by('happened_at')
        for e in oom_qs:
            oom_events[(e.workload_id, e.container.name)].append(e)

        for stat in models.Summary.get_all(options['force_update']):
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

            for oom in oom_events[(stat.workload.id, stat.container_name)]:
                msg = f'  OOM {oom.happened_at}'
                if oom.target_pid:
                    msg += f' target:{oom.target_comm}({oom.target_pid})'
                if oom.victim_pid:
                    msg += f' victim:{oom.victim_comm}({oom.victim_pid})'
                if oom.container.memory_limit_mi:
                    msg += f' limit:{oom.container.memory_limit_mi} Mi'
                print(msg)
