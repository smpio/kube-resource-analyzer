from django.core.management.base import BaseCommand

from kra import models


class Command(BaseCommand):
    help = 'Get OOM events'

    def handle(self, *args, **options):
        qs = models.OOMEvent.objects\
            .order_by('happened_at')\
            .select_related('container__pod__workload')
        for ev in qs.iterator():
            wl = ev.container.pod.workload
            if ev.victim_comm:
                msg = f'killed {ev.victim_comm}({ev.victim_pid or "?"})'
            elif ev.target_comm:
                msg = f'kill {ev.target_comm}({ev.target_pid or "?"})'
            else:
                msg = ''
            print(f'{ev.happened_at} {wl.kind.name} {wl.namespace}/{wl.name}: {msg}')
