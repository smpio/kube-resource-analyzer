import hashlib
import datetime

import kubernetes.client as api

from kra.celery import task
from kra.oom import as_aware_datetime


@task
def create_event(reason: str,
                 involved_object: dict,
                 message: str,
                 timestamp: datetime.datetime,
                 namespace: str = ''):
    # Kubernetes requires RFC3339 with an offset, including events loaded from DB.
    timestamp = as_aware_datetime(timestamp)
    # Accept references in tasks queued by the previous version during rollout.
    if isinstance(involved_object, dict):
        involved_object = api.V1ObjectReference(**involved_object)
    msg_hash = hashlib.sha1(message.encode()).hexdigest()[:8]
    event_name = f'{involved_object.name}.{int(timestamp.timestamp())}.{msg_hash}'
    event = api.CoreV1Event(
        metadata=api.V1ObjectMeta(
            name=event_name,
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
