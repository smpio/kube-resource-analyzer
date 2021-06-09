from django.db.models.signals import post_save


def handle_oom_event_saved(sender, instance, **kwargs):
    from kra import tasks
    tasks.make_suggestion.delay(instance.container.pod.workload_id, instance.container.name)


def install():
    from . import models
    post_save.connect(handle_oom_event_saved, sender=models.OOMEvent)
