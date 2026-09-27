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
            # A timeout or a lost response does not tell us whether Kubernetes
            # accepted the JSON patch.  Read the workload again before recording
            # a failure, so a completed patch is never reported as failed solely
            # because its response was lost.
            try:
                result_data = _reconcile_adjustment(adj, cause=err)
            except Exception as reconcile_err:
                adj.result = models.OperationResult.objects.create(
                    finished_at=timezone.now(),
                    error=_format_apply_error(err, reconcile_err),
                )
                log.exception('Failed to apply adjustment %s', adj)
            else:
                adj.result = models.OperationResult.objects.create(
                    finished_at=timezone.now(), data=result_data)
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
    workload_obj = kube.get_workload_obj(wl)
    resource_version = workload_obj.metadata.resource_version
    if not resource_version:
        raise ValueError(f'Workload {wl} has no resourceVersion')

    adj.resource_version = resource_version
    adj.save(update_fields=['resource_version'])

    containers = kube.get_workload_containers_from_obj(workload_obj, wl.kind)

    container_adjustments = {ca.container_name: ca for ca in adj.containers.all()}
    containers_by_name = {container.name: container for container in containers}
    unknown_containers = sorted(set(container_adjustments) - set(containers_by_name))
    if unknown_containers:
        raise ValueError(f'Containers not found in {wl}: {", ".join(unknown_containers)}')

    resource_patch = [
        _get_json_patch_op(idx, wl.kind, container, container_adjustments[container.name])
        for idx, container in enumerate(containers)
        if container.name in container_adjustments
    ]
    if not resource_patch:
        raise ValueError(f'Adjustment {adj.id} has no containers')
    json_patch = [{
        'op': 'test',
        'path': '/metadata/resourceVersion',
        'value': resource_version,
    }] + resource_patch

    log.debug('Applying patch to %s: %s', wl, json_patch)
    patch_func = kube.patch_funcs[wl.kind]
    patch_func(wl.name, wl.namespace, json_patch)
    verified_resource_version = _verify_adjustment(adj)
    return {
        'target': 'kubernetes',
        'containers': sorted(container_adjustments),
        'resource_version': verified_resource_version,
        'verified': True,
    }


def _reconcile_adjustment(adj, cause):
    resource_version = _verify_adjustment(adj)
    log.warning(
        'Adjustment %s patch raised %s but the desired resources are present at resourceVersion %s',
        adj, cause, resource_version,
    )
    return {
        'target': 'kubernetes',
        'containers': sorted(c.container_name for c in adj.containers.all()),
        'resource_version': resource_version,
        'verified': True,
        'reconciled_after_error': True,
        'original_error': str(cause),
    }


def _verify_adjustment(adj):
    workload_obj = kube.get_workload_obj(adj.workload)
    containers_by_name = {
        container.name: container
        for container in kube.get_workload_containers_from_obj(workload_obj, adj.workload.kind)
    }
    mismatches = []
    for container_adjustment in adj.containers.all():
        container = containers_by_name.get(container_adjustment.container_name)
        if container is None:
            mismatches.append(f'{container_adjustment.container_name}: container not found')
            continue
        resources = kube.get_container_resources(container)
        if (container_adjustment.new_memory_limit_mi is not None and
                resources.get('memory_limit_mi') != container_adjustment.new_memory_limit_mi):
            mismatches.append(f'{container.name}: memory limit was not applied')
        if (container_adjustment.new_cpu_request_m is not None and
                resources.get('cpu_request_m') != container_adjustment.new_cpu_request_m):
            mismatches.append(f'{container.name}: CPU request was not applied')
    if mismatches:
        raise ValueError('; '.join(mismatches))
    return workload_obj.metadata.resource_version


def _format_apply_error(apply_error, reconcile_error):
    return f'Patch failed: {apply_error}; reconciliation did not confirm the desired resources: {reconcile_error}'


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
