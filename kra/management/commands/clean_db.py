import logging

from django.db import connection
from django.conf import settings
from django.utils import timezone
from django.core.management.base import BaseCommand

from kra import models

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Removes old db entries'

    def handle(self, *args, **options):
        delete_before = timezone.now() - settings.MAX_RETENTION

        deleted, _ = models.Adjustment.objects.filter(done_at__lt=delete_before).delete()
        vacuum(models.Adjustment)
        log.info('Deleted %d adjustments', deleted)

        deleted, _ = models.OOMEvent.objects.filter(happened_at__lt=delete_before).delete()
        vacuum(models.OOMEvent)
        log.info('Deleted %d OOM events', deleted)

        deleted, _ = models.ResourceUsage.objects.filter(measured_at__lt=delete_before).delete()
        vacuum(models.ResourceUsage)
        log.info('Deleted %d resource usage measurements', deleted)

        deleted, _ = models.Pod.objects.filter(gone_at__lt=delete_before).delete()
        vacuum(models.Pod)
        log.info('Deleted %d pods', deleted)

        deleted, _ = models.Workload.objects.filter(pod=None).delete()
        vacuum(models.Workload)
        log.info('Deleted %d workloads', deleted)

        vacuum(models.Summary)
        vacuum(models.Suggestion)


def vacuum(model):
    with connection.cursor() as c:
        c.execute(f'VACUUM (ANALYZE) {model._meta.db_table}')
