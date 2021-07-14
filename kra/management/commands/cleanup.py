from django.db import connection
from django.conf import settings
from django.utils import timezone
from django.core.management.base import BaseCommand

from kra import tasks
from kra import models


class Command(BaseCommand):
    help = 'Removes old db entries, runs missed tasks'

    def handle(self, *args, **options):
        apply_missed_adjustments()
        clean_db()


def apply_missed_adjustments():
    now = timezone.now()
    counter = 0
    for adj_id in models.Adjustment.objects.filter(result=None, scheduled_for__lt=now).values_list('id', flat=True):
        counter += 1
        tasks.apply_adjustment(adj_id)
    print('Queued %d adjustments')


def clean_db():
    delete_before = timezone.now() - settings.MAX_RETENTION

    deleted = delete(models.Adjustment.objects.filter(result__finished_at__lt=delete_before))
    print(f'Deleted {deleted} adjustments')

    deleted = delete(models.OperationResult.objects.filter(finished_at__lt=delete_before))
    print(f'Deleted {deleted} operation results')

    deleted = delete(models.OOMEvent.objects.filter(happened_at__lt=delete_before))
    print(f'Deleted {deleted} OOM events')

    deleted = delete(models.ResourceUsage.objects.filter(measured_at__lt=delete_before))
    print(f'Deleted {deleted} resource usage measurements')

    deleted = delete(models.Pod.objects.filter(gone_at__lt=delete_before))
    print(f'Deleted {deleted} pods')

    deleted = delete(models.Workload.objects.filter(pod=None))
    print(f'Deleted {deleted} workloads')

    print('VACUUM ANALYZE')
    with connection.cursor() as c:
        c.execute(f'VACUUM (ANALYZE)')


def delete(qs):
    total, per_model = qs.delete()
    return per_model.get(qs.model._meta.label, 0)
