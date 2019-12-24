import logging

from django.core.management.base import BaseCommand

from kra import models

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Get OOM events'

    def handle(self, *args, **options):
        for ev in models.OOMEvent.objects.order_by('happened_at').iterator():
            wl = ev.container.pod.workload
            if ev.victim_pid:
                msg = f'(Killed {ev.victim_comm} {ev.victim_pid})'
            elif ev.target_pid:
                msg = f'(Kill {ev.target_comm} {ev.target_pid})'
            else:
                msg = ''
            print(f'{ev.happened_at} {wl.kind.name} {wl.namespace}/{wl.name} {msg}')
