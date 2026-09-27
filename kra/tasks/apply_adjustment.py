import logging

from django.utils import timezone

from utils.lock import get_lock

from kra import kube
from kra import models
from kra.celery import task

log = logging.getLogger(__name__)


@task
def apply_adjustment(adj_id):
    with get_lock(f'adjustment:{adj_id}') as is_locked:
        adj = models.Adjustment.objects.select_related('workload').get(id=adj_id)
        if not is_locked:
            log.info('Adjustment %s already locked', adj)
            return

        if adj.result_id is not None:
            log.info('Adjustment %s already done', adj)
            return

        if adj.scheduled_for > timezone.now():
            log.info('Schedule adjustment %s for %s', adj, adj.scheduled_for)
            apply_adjustment.apply_async(args=(adj.id,), eta=adj.scheduled_for)
            return

        try:
            result_data = _apply_adjustment(adj)
        except Exception as err:
            adj.result = models.OperationResult.objects.create(finished_at=timezone.now(), error=str(err))
            log.exception('Failed to apply adjustment %s', adj)
        else:
            adj.result = models.OperationResult.objects.create(finished_at=timezone.now(), data=result_data)

        adj.save(update_fields=['result'])

        if adj.result.error is None:
            models.Suggestion.objects.filter(summary__workload_id=adj.workload_id).delete()
            for ca in adj.containers.all():
                summary_update = {}
                if ca.new_memory_limit_mi is not None:
                    summary_update['memory_limit_mi'] = ca.new_memory_limit_mi
                if ca.new_cpu_request_m is not None:
                    summary_update['cpu_request_m'] = ca.new_cpu_request_m
                if summary_update:
                    models.Summary.objects\
                        .filter(workload_id=adj.workload_id, container_name=ca.container_name)\
                        .update(**summary_update)


def _apply_adjustment(adj):
    wl = adj.workload
    containers = kube.get_workload_containers(wl)

    container_adjustments = {ca.container_name: ca for ca in adj.containers.all()}
    containers_by_name = {container.name: container for container in containers}
    unknown_containers = sorted(set(container_adjustments) - set(containers_by_name))
    if unknown_containers:
        raise ValueError(f'Containers not found in {wl}: {", ".join(unknown_containers)}')

    json_patch = [
        _get_json_patch_op(idx, wl.kind, container, container_adjustments[container.name])
        for idx, container in enumerate(containers)
        if container.name in container_adjustments
    ]
    if not json_patch:
        raise ValueError(f'Adjustment {adj.id} has no containers')

    log.debug('Applying patch to %s: %s', wl, json_patch)
    patch_func = kube.patch_funcs[wl.kind]
    patch_func(wl.name, wl.namespace, json_patch)
    return {
        'target': 'kubernetes',
        'containers': sorted(container_adjustments),
    }


def _get_json_patch_op(idx, kind, container, container_adjustment):
    path = '/'.join(kube.containers_paths[kind])

    resources = _get_resources_value(container)
    if container_adjustment.new_memory_limit_mi is not None:
        resources.setdefault('limits', {})['memory'] = f'{container_adjustment.new_memory_limit_mi}Mi'
    if container_adjustment.new_cpu_request_m is not None:
        resources.setdefault('requests', {})['cpu'] = f'{container_adjustment.new_cpu_request_m}m'

    return {
        'op': 'replace' if container.resources is not None else 'add',
        'path': f'/{path}/{idx}/resources',
        'value': resources,
    }


def _get_resources_value(container):
    if container.resources is None:
        return {}

    # V1ResourceRequirements.to_dict() returns every supported field, including
    # fields introduced after this project.  Drop only unset values so a complete
    # resources replacement cannot discard existing limits, requests or claims.
    return {key: value for key, value in container.resources.to_dict().items() if value is not None}
