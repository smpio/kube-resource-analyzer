from kra import models
from kra.celery import task


@task
def save_non_collected_oom(pod_uid, container_runtime_id, happened_at, **data):
    c = models.Container.objects.get(pod__uid=pod_uid, runtime_id=container_runtime_id)
    oom = models.OOMEvent(container=c, happened_at=happened_at, **data)
    oom.save_if_not_exist()
