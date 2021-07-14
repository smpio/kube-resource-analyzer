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
            msg = ' CRIT' if ev.is_critical else ''
            if ev.victim_comm:
                msg += f' killed {ev.victim_comm}'
                if ev.victim_pid:
                    msg += f'({ev.victim_pid})'
            if ev.target_comm:
                msg += f' kill {ev.target_comm}'
                if ev.target_pid:
                    msg += f'({ev.target_pid})'
            print(f'{ev.happened_at} {wl.kind.name} {wl.namespace}/{wl.name}:{msg}')
