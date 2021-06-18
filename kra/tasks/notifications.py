import datetime

import requests
from django.conf import settings
import kubernetes.client as api

from kra.celery import task


@task
def post(message, username='KRA'):
    if not settings.DISCORD_WEBHOOK_URL:
        return
    resp = requests.post(settings.DISCORD_WEBHOOK_URL, json={
        'username': username,
        'content': message,
    })
    resp.raise_for_status()


@task
def create_event(reason: str,
                 involved_object: api.V1ObjectReference,
                 message: str,
                 timestamp: datetime.datetime,
                 namespace: str = ''):
    event = api.V1Event(
        metadata=api.V1ObjectMeta(
            name=f'{involved_object.name}.{int(timestamp.timestamp() * 1000000)}',
            namespace=namespace,
        ),
        involved_object=involved_object,
        reason=reason,
        message=message,
        first_timestamp=timestamp,
        last_timestamp=timestamp,
        count=1,
        type='Warning',
        source=api.V1EventSource(
            component='kube-resources-analyzer',
        ),
    )

    v1 = api.CoreV1Api()
    v1.create_namespaced_event(namespace, event)
