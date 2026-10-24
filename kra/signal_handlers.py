from django.db.models.signals import post_save
from django.db import transaction


def handle_oom_event_saved(sender, instance, created, **kwargs):
    from kra import tasks

    oom = instance
    container = oom.container
    pod = container.pod

    if pod.workload_id is not None:
        transaction.on_commit(lambda: tasks.make_suggestion.delay(pod.workload_id, container.name))

    promoted = kwargs.get('update_fields') == frozenset({'is_critical'}) and oom.is_critical
    if not created and not promoted:
        return

    # SDK models carry in-cluster token-refresh callbacks and cannot be pickled.
    ref = {'kind': 'Pod', 'name': pod.name, 'namespace': pod.namespace}

    msg = f'OOM in container {container.name} of pod {pod.namespace}/{pod.name}, '\
          f'comm: {oom.victim_comm}({oom.victim_pid})'
    if oom.is_critical:
        msg = 'CRITICAL ' + msg
    transaction.on_commit(lambda: tasks.notifications.create_event.apply_async(
        args=('ContainerOOM', ref, msg, oom.happened_at, pod.namespace),
        serializer='json',
    ))


def install():
    from . import models
    post_save.connect(handle_oom_event_saved, sender=models.OOMEvent)
