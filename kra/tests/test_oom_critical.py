from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest import mock

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from kubernetes import client

from kra import models, tasks
from kra.collectors.oom import HandlerThread
from kra.collectors.pods import update_containers


POD_UID = '12345678-1234-1234-1234-123456789abc'
OLD_ID = 'a' * 64
NEW_ID = 'b' * 64


class OOMCriticalFixtures:

    def setUp(self):
        super().setUp()
        self.now = timezone.now().replace(microsecond=0)
        self.pod = models.Pod.objects.create(
            uid=POD_UID, namespace='example', name='worker', spec_hash='',
            started_at=self.now - timedelta(hours=1),
        )
        self.container = models.Container.objects.create(
            pod=self.pod, name='main', runtime_id=OLD_ID,
            started_at=self.pod.started_at, memory_limit_mi=32,
        )
        self.suggestion = mock.patch.object(tasks.make_suggestion, 'delay').start()
        self.notify = mock.patch.object(tasks.notifications.create_event, 'apply_async').start()
        self.addCleanup(mock.patch.stopall)

    def oom(self, timestamp=None):
        event = SimpleNamespace(
            metadata=SimpleNamespace(name='node.oom'),
            involved_object=SimpleNamespace(name='node'),
            last_timestamp=timestamp or self.now,
            message=f'pid:123\nproc:python\ntaskcg:/kubepods/pod{POD_UID}/{OLD_ID}',
        )
        HandlerThread(None)._handle(event)
        return models.OOMEvent.objects.latest('id')

    def observe(self, *, restarted=False, waiting=False, reason='OOMKilled',
                finished_at=None, pod=None):
        terminated = client.V1ContainerStateTerminated(
            container_id=f'containerd://{OLD_ID}', exit_code=137, reason=reason,
            started_at=self.container.started_at, finished_at=finished_at or self.now,
        )
        state = client.V1ContainerState(terminated=terminated)
        last_state = client.V1ContainerState()
        current_id = f'containerd://{OLD_ID}'
        if restarted or waiting:
            last_state = state
            current_id = None if waiting else f'containerd://{NEW_ID}'
            state = client.V1ContainerState(waiting=client.V1ContainerStateWaiting(reason='CrashLoopBackOff')) \
                if waiting else client.V1ContainerState(
                    running=client.V1ContainerStateRunning(started_at=self.now + timedelta(seconds=1)),
                )
        status = client.V1ContainerStatus(
            name='main', image='python', image_id='image', ready=not waiting,
            restart_count=int(restarted or waiting), container_id=current_id,
            state=state, last_state=last_state,
        )
        observed = client.V1Pod(
            metadata=client.V1ObjectMeta(uid=str((pod or self.pod).uid), name='worker', namespace='example'),
            spec=client.V1PodSpec(containers=[client.V1Container(name='main')]),
            status=client.V1PodStatus(container_statuses=[status]),
        )
        update_containers(observed, pod or self.pod)


class OOMCriticalTests(OOMCriticalFixtures, TestCase):
    def test_event_before_pod_status_is_promoted_and_notified_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            event = self.oom()
        self.assertFalse(event.is_critical)
        self.assertEqual(self.notify.call_count, 1)
        with self.captureOnCommitCallbacks(execute=True):
            self.observe(restarted=True)
            self.observe(restarted=True)
        event.refresh_from_db()
        self.assertTrue(event.is_critical)
        self.assertEqual(self.notify.call_count, 2)
        self.assertTrue(self.notify.call_args.kwargs['args'][2].startswith('CRITICAL '))
        self.container.refresh_from_db()
        self.assertEqual(self.container.oom_killed_at, self.now)
        self.assertEqual(self.container.finished_at, self.now)
        self.assertIsNone(models.Container.objects.get(runtime_id=NEW_ID).oom_killed_at)

    def test_pod_status_before_event_is_critical_on_first_save(self):
        self.observe()
        with self.captureOnCommitCallbacks(execute=True):
            event = self.oom()
        self.assertTrue(event.is_critical)
        self.assertEqual(self.notify.call_count, 1)
        self.assertTrue(self.notify.call_args.kwargs['args'][2].startswith('CRITICAL '))

    def test_waiting_without_current_runtime_id_uses_last_state(self):
        event = self.oom()
        self.observe(waiting=True)
        event.refresh_from_db()
        self.assertTrue(event.is_critical)

    def test_child_oom_with_live_container_stays_noncritical(self):
        event = self.oom()
        event.refresh_from_db()
        self.assertFalse(event.is_critical)

    def test_later_oom_restart_does_not_promote_earlier_child_oom(self):
        earlier = self.oom(self.now - timedelta(minutes=5))
        latest = self.oom()
        self.observe(restarted=True)
        earlier.refresh_from_db()
        latest.refresh_from_db()
        self.assertFalse(earlier.is_critical)
        self.assertTrue(latest.is_critical)

    def test_exit_137_without_oom_killed_evidence_stays_noncritical(self):
        event = self.oom()
        self.observe(restarted=True, reason='Error')
        event.refresh_from_db()
        self.assertFalse(event.is_critical)

    def test_normal_deletion_cleanup_is_not_oom_evidence(self):
        self.container.finished_at = self.now
        self.container.save(update_fields=['finished_at'])
        self.assertFalse(self.oom().is_critical)

    def test_same_pod_name_with_different_uid_cannot_promote_old_event(self):
        event = self.oom()
        replacement = models.Pod.objects.create(
            uid='87654321-4321-4321-4321-cba987654321', namespace='example',
            name='worker', spec_hash='', started_at=self.now,
        )
        self.observe(pod=replacement)
        event.refresh_from_db()
        self.assertFalse(event.is_critical)

    def test_timestamp_precision_tolerance(self):
        self.observe(finished_at=self.now + timedelta(seconds=2))
        self.assertTrue(self.oom().is_critical)

    def test_old_child_event_arriving_after_termination_stays_noncritical(self):
        self.observe()
        self.assertFalse(self.oom(self.now - timedelta(minutes=5)).is_critical)

    def test_rolled_back_event_does_not_publish_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                self.oom()
                transaction.set_rollback(True)
        self.notify.assert_not_called()
        self.suggestion.assert_not_called()
        self.assertFalse(models.OOMEvent.objects.exists())


class OOMCriticalConcurrencyTests(OOMCriticalFixtures, TransactionTestCase):
    def check_concurrent_collectors(self, termination_first):
        if connection.vendor != 'postgresql':
            self.skipTest('This regression exercises PostgreSQL row locks')
        locked = Event()
        release = Event()
        peer_connected = Event()
        peer_pid = []

        def first():
            try:
                with transaction.atomic():
                    models.Container.objects.select_for_update().get(pk=self.container.pk)
                    self.observe() if termination_first else self.oom()
                    locked.set()
                    if not release.wait(5):
                        raise TimeoutError('Test did not release the container lock')
            finally:
                connections.close_all()

        def second():
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    peer_pid.append(cursor.fetchone()[0])
                peer_connected.set()
                self.oom() if termination_first else self.observe()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(first)
            try:
                self.assertTrue(locked.wait(5))
                b = executor.submit(second)
                self.assertTrue(peer_connected.wait(5))
                blocked = False
                deadline = monotonic() + 3
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_blocking_pids(%s)', [peer_pid[0]])
                        blocked = bool(cursor.fetchone()[0])
                    if blocked:
                        break
                    sleep(0.01)
                self.assertTrue(blocked, 'Peer collector did not wait for the shared container row lock')
            finally:
                release.set()
            a.result(timeout=5)
            b.result(timeout=5)
        self.assertTrue(models.OOMEvent.objects.get().is_critical)

    def test_oom_handler_waits_for_in_flight_pod_update(self):
        self.check_concurrent_collectors(termination_first=True)

    def test_pod_update_waits_for_in_flight_oom_insert(self):
        self.check_concurrent_collectors(termination_first=False)
