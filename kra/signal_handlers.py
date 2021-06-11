from django.db.models.signals import post_save


def handle_oom_event_saved(sender, instance, **kwargs):
    from kra import tasks

    oom = instance
    container = oom.container
    pod = container.pod

    tasks.make_suggestion.delay(pod.workload_id, container.name)
    tasks.notifications.post.delay(
        f'OOM: {pod.namespace}/{pod.name}, container: {container.name}, comm: {oom.victim_comm}')


def install():
    from . import models
    post_save.connect(handle_oom_event_saved, sender=models.OOMEvent)
