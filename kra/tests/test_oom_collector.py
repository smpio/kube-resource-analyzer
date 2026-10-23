import datetime
from types import SimpleNamespace
from unittest import TestCase, mock

from kubernetes import client
from kombu.serialization import dumps, loads

from kra import tasks
from kra.collectors.oom import get_container, parse_event_message
from kra.signal_handlers import handle_oom_event_saved
from kra.tasks.notifications import create_event
from kra.utils import parse_cgroup


POD_UID = '12345678-1234-1234-1234-123456789abc'
CONTAINER_ID = '0123456789abcdef' * 4


class CgroupTests(TestCase):
    def test_extracts_container_and_pod_from_both_drivers_and_all_qos_classes(self):
        for qos in ('', 'burstable', 'besteffort'):
            cgroupfs = f'/kubepods/{qos + "/" if qos else ""}pod{POD_UID}/{CONTAINER_ID}'
            prefix = f'kubepods-{qos}' if qos else 'kubepods'
            systemd = (
                f'/kubepods.slice/{prefix + ".slice/" if qos else ""}'
                f'{prefix}-pod{POD_UID.replace("-", "_")}.slice/'
                f'cri-containerd-{CONTAINER_ID}.scope'
            )
            for path in (cgroupfs, systemd):
                with self.subTest(path=path):
                    self.assertEqual(parse_cgroup(path), (POD_UID, CONTAINER_ID))

    def test_ignores_host_and_incomplete_cgroup_paths(self):
        for path in ('/', '/system.slice/sshd.service', '/kubepods.slice',
                     f'/kubepods/pod{POD_UID}', f'/kubepods/pod{POD_UID}/{CONTAINER_ID}/child',
                     f'/kubepods-pod{POD_UID}.slice/cri-containerd-not-hex.scope'):
            with self.subTest(path=path):
                self.assertEqual(parse_cgroup(path), (None, None))

    def test_monitor_message_resolves_the_normalized_systemd_identity(self):
        path = (
            f'/kubepods.slice/kubepods-burstable.slice/'
            f'kubepods-burstable-pod{POD_UID.replace("-", "_")}.slice/'
            f'cri-containerd-{CONTAINER_ID}.scope'
        )
        cgroup, comm, pid = parse_event_message(
            f'pid:12345\nproc:worker\ntaskcg:{path}\noomcg:/kubepods.slice'
        )
        self.assertEqual((comm, pid), ('worker', 12345))
        with mock.patch('kra.collectors.oom.models.Container.objects.get') as get:
            self.assertIs(get_container(cgroup), get.return_value)
        get.assert_called_once_with(runtime_id=CONTAINER_ID, pod__uid=POD_UID)


class OOMNotificationTests(TestCase):
    def test_signal_serializes_with_in_cluster_configuration_and_worker_creates_event(self):
        # The SDK attaches this non-picklable hook to reference models in-cluster.
        configuration = client.Configuration()
        configuration.refresh_api_key_hook = lambda _: None
        previous = client.Configuration._default
        client.Configuration.set_default(configuration)
        self.addCleanup(client.Configuration.set_default, previous)
        timestamp = datetime.datetime(2026, 10, 23, 0, 26, 18, tzinfo=datetime.timezone.utc)
        pod = SimpleNamespace(name='worker-abc', namespace='example', workload_id=7)
        container = SimpleNamespace(name='main', pod=pod)
        oom = SimpleNamespace(container=container, happened_at=timestamp,
                              victim_comm='worker', victim_pid=12345, is_critical=True)
        broker_payload = []

        def publish(*, args, serializer):
            # Exercise the actual Kombu encoder/decoder, not a mocked pickle call.
            content_type, encoding, payload = dumps(args, serializer=serializer)
            broker_payload.append(loads(payload, content_type, encoding, accept={content_type}))
            self.assertEqual(serializer, 'json')

        with mock.patch.object(tasks.make_suggestion, 'delay') as suggestion, \
                mock.patch('kra.tasks.notifications.create_event.apply_async', side_effect=publish):
            handle_oom_event_saved(None, oom, created=True)
        suggestion.assert_called_once_with(7, 'main')
        self.assertEqual(len(broker_payload), 1)

        with mock.patch('kra.tasks.notifications.api.CoreV1Api') as core:
            create_event.run(*broker_payload[0])
        namespace, event = core.return_value.create_namespaced_event.call_args.args
        self.assertEqual(namespace, 'example')
        self.assertEqual(event.reason, 'ContainerOOM')
        self.assertEqual(event.involved_object.kind, 'Pod')
        self.assertEqual(event.involved_object.name, 'worker-abc')
        self.assertEqual(event.involved_object.namespace, 'example')
        self.assertEqual(event.first_timestamp, timestamp)
        self.assertEqual(event.last_timestamp, timestamp)
        self.assertEqual(event.message, 'CRITICAL OOM in container main of pod example/worker-abc, comm: worker(12345)')

    def test_worker_accepts_sdk_reference_already_queued_by_old_version(self):
        reference = client.V1ObjectReference(kind='Pod', name='worker-abc', namespace='example')
        with mock.patch('kra.tasks.notifications.api.CoreV1Api') as core:
            create_event.run('ContainerOOM', reference, 'OOM',
                             datetime.datetime(2026, 10, 23, tzinfo=datetime.timezone.utc), 'example')
        self.assertIs(core.return_value.create_namespaced_event.call_args.args[1].involved_object, reference)
