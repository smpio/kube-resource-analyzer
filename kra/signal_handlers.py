import kubernetes.client as api
from django.db.models.signals import post_save


def handle_oom_event_saved(sender, instance, created, **kwargs):
    from kra import tasks

    oom = instance
    container = oom.container
    pod = container.pod

    tasks.make_suggestion.delay(pod.workload_id, container.name)

    if not created:
        return

    ref = api.V1ObjectReference(
        kind='Pod',
        name=pod.name,
        namespace=pod.namespace,
    )
    msg = f'OOM in container {container.name} of pod {pod.namespace}/{pod.name}, comm: {oom.victim_comm}'
    tasks.notifications.create_event.apply_async(
        args=('ContainerOOM', ref, msg, oom.happened_at, pod.namespace),
        serializer='pickle',
    )


def install():
    from . import models
    post_save.connect(handle_oom_event_saved, sender=models.OOMEvent)
