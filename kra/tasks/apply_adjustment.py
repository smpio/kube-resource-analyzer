import logging

from django.utils import timezone

from utils.lock import get_lock

from kra import kube
from kra import models
from kra.celery import task

log = logging.getLogger(__name__)


@task
def apply_adjustment(adj):
    if not isinstance(adj, models.Adjustment):
        adj = models.Adjustment.objects.select_related('workload').get(id=adj)

    with get_lock(f'adjustment:{adj.id}') as is_locked:
        if not is_locked:
            log.info('Adjustment %s already locked', adj)
            return

        if adj.result_id is not None:
            log.info('Adjustment %s already finished', adj)
            return

        if adj.scheduled_for > timezone.now():
            log.info('Schedule adjustment %s for %s', adj, adj.scheduled_for)
            apply_adjustment.apply_async(args=(adj.id,), eta=adj.scheduled_for)
            return

        try:
            _apply_adjustment(adj)
        except Exception as err:
            adj.result = models.OperationResult.objects.create(finished_at=timezone.now(), error=str(err))
        else:
            adj.result = models.OperationResult.objects.create(finished_at=timezone.now())

        adj.save(update_fields=['result'])

        models.Suggestion.objects.filter(summary__workload_id=adj.workload_id).delete()
        for ca in adj.containers.all():
            models.Summary.objects\
                .filter(workload_id=adj.workload_id, container_name=ca.container_name)\
                .update(memory_limit_mi=ca.new_memory_limit_mi, cpu_request_m=ca.new_cpu_request_m)


def _apply_adjustment(adj):
    wl = adj.workload

    read_obj = kube.read_funcs[wl.kind]
    obj = read_obj(wl.name, wl.namespace)
    containers = _get_containers(obj, wl.kind)

    container_adjustments = {ca.container_name: ca for ca in adj.containers.all()}
    json_patch = [_get_json_patch_op(idx, wl.kind, container_adjustments[c.name]) for (idx, c) in enumerate(containers)]

    patch_func = kube.patch_funcs[wl.kind]
    patch_func(wl.name, wl.namespace, json_patch)


def _get_containers(obj, kind):
    path = kube.containers_paths[kind]
    for part in path:
        obj = getattr(obj, part)
    return obj


def _get_json_patch_op(idx, kind, container_adjustment):
    path = '/'.join(kube.containers_paths[kind])
    return {
        'op': 'replace',
        'path': f'/{path}/{idx}/resources',
        'value': {
            'limits': {
                'memory': f'{container_adjustment.new_memory_limit_mi}Mi',
            },
            'requests': {
                'cpu': f'{container_adjustment.new_cpu_request_m}m',
            }
        }
    }
