from django.db import connection
from django.conf import settings
from django.utils import timezone
from django.core.management.base import BaseCommand

from kra import models


class Command(BaseCommand):
    help = 'Removes old db entries'

    def handle(self, *args, **options):
        delete_before = timezone.now() - settings.MAX_RETENTION

        deleted, _ = models.Adjustment.objects.filter(done_at__lt=delete_before).delete()
        vacuum(models.Adjustment)
        print(f'Deleted {deleted} adjustments')

        deleted, _ = models.OOMEvent.objects.filter(happened_at__lt=delete_before).delete()
        vacuum(models.OOMEvent)
        print(f'Deleted {deleted} OOM events')

        deleted, _ = models.ResourceUsage.objects.filter(measured_at__lt=delete_before).delete()
        vacuum(models.ResourceUsage)
        print(f'Deleted {deleted} resource usage measurements')

        deleted, _ = models.Pod.objects.filter(gone_at__lt=delete_before).delete()
        vacuum(models.Pod)
        print(f'Deleted {deleted} pods')

        deleted, _ = models.Workload.objects.filter(pod=None).delete()
        vacuum(models.Workload)
        print(f'Deleted {deleted} workloads')

        vacuum(models.Summary)
        vacuum(models.Suggestion)


def vacuum(model):
    with connection.cursor() as c:
        c.execute(f'VACUUM (ANALYZE) {model._meta.db_table}')
