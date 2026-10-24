import uuid
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from kubernetes import client

from kra import models
from kra.collectors.pods import update_pod
from kra.oom import as_aware_datetime


class PodRegistrationTests(TestCase):
    def test_registers_statefulset_revisions_up_to_the_label_value_limit(self):
        workload = models.Workload.objects.create(
            namespace='argocd', name='argocd-application-controller',
            kind=models.WorkloadKind.StatefulSet,
        )
        revisions = ['argocd-application-controller-79f74f9db8', 'controller-' + 'a' * 52]
        for revision in revisions:
            with self.subTest(length=len(revision)):
                uid = str(uuid.uuid4())
                started_at = as_aware_datetime(timezone.now())
                pod = client.V1Pod(
                    metadata=client.V1ObjectMeta(
                        uid=uid, namespace='argocd', name='argocd-application-controller-0',
                        labels={'controller-revision-hash': revision},
                    ),
                    spec=client.V1PodSpec(containers=[client.V1Container(name='controller')]),
                    status=client.V1PodStatus(
                        start_time=started_at,
                        container_statuses=[client.V1ContainerStatus(
                            name='controller', container_id=f'containerd://{uuid.uuid4().hex}',
                            image='argocd', image_id='image', ready=True, restart_count=0,
                            state=client.V1ContainerState(
                                running=client.V1ContainerStateRunning(started_at=started_at),
                            ),
                        )],
                    ),
                )
                with mock.patch('kra.collectors.pods.get_workload_from_pod', return_value=workload):
                    update_pod(pod)
                    update_pod(pod)
                stored = models.Pod.objects.get(uid=uid)
                self.assertEqual(stored.spec_hash, revision)
                self.assertEqual(stored.workload, workload)
                self.assertEqual(stored.container_set.count(), 1)
