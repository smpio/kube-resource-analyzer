import logging

from django.db import transaction
from django.utils import timezone

from kra import gitops, kube, models
from kra.celery import task
from kra.tasks.apply_adjustment import _verify_adjustment
from kra.tasks.make_suggestion import make_suggestion
from utils.lock import get_lock

log = logging.getLogger(__name__)
WAITING_STATUSES = ('awaiting_argo_sync', 'awaiting_pull_request_merge')


@task
def reconcile_gitops_adjustments():
    with get_lock('gitops-reconciliation') as locked:
        if not locked:
            return
        pending = models.Adjustment.objects.filter(
            result__error__isnull=True, result__data__target='git',
            result__data__sync_status__in=WAITING_STATUSES,
        ).values_list('id', flat=True)
        for adjustment_id in pending.iterator():
            try:
                reconcile_adjustment(adjustment_id)
            except Exception:
                # Keep pending records so transient API failures are retried next cycle.
                log.exception('Failed to reconcile GitOps adjustment %s', adjustment_id)


def reconcile_adjustment(adjustment_id):
    with get_lock(f'adjustment:{adjustment_id}') as locked:
        if not locked:
            return
        adj = models.Adjustment.objects.select_related('workload', 'result').get(id=adjustment_id)
        result = adj.result
        if (result is None or result.error is not None or
                (result.data or {}).get('target') != 'git' or
                result.data.get('sync_status') not in WAITING_STATUSES):
            return
        revision = gitops.synced_revision(result.data)
        if revision is None:
            return
        obj = kube.get_workload_obj(adj.workload)
        tracking_id = (obj.metadata.annotations or {}).get(gitops.TRACKING_ID, '')
        if gitops._application_name(tracking_id, adj.workload) != result.data['application']:
            raise gitops.GitOpsError('Workload is no longer managed by the original Application')
        resource_version = _verify_adjustment(adj)
        with transaction.atomic():
            # Serialize with other reconciliations of this result and summary updates.
            result = models.OperationResult.objects.select_for_update().get(id=result.id)
            if result.data.get('sync_status') not in WAITING_STATUSES:
                return
            for ca in adj.containers.all():
                summary = models.Summary.objects.select_for_update().filter(
                    workload_id=adj.workload_id, container_name=ca.container_name).first()
                if summary is None:
                    continue
                fields = []
                if ca.new_memory_limit_mi is not None:
                    summary.memory_limit_mi = ca.new_memory_limit_mi
                    fields.append('memory_limit_mi')
                if ca.new_cpu_request_m is not None:
                    summary.cpu_request_m = ca.new_cpu_request_m
                    fields.append('cpu_request_m')
                summary.save(update_fields=fields)
                # Recompute rather than deleting an outstanding CPU recommendation or
                # a newer recommendation triggered by another OOM.
                make_suggestion(adj.workload_id, ca.container_name, make_missing_summary=False)
            result.data = {
                **result.data, 'sync_status': 'synced', 'verified': True,
                'synced_revision': revision, 'synced_at': timezone.now().isoformat(),
                'resource_version': resource_version,
            }
            result.finished_at = timezone.now()
            result.save(update_fields=['data', 'finished_at'])
        log.info('GitOps adjustment %s confirmed at revision %s', adj.id, revision)
