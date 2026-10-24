import re
import queue
import logging
import threading

import kubernetes
import kubernetes.client
from django.db import transaction

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import fix_long_connections

from kra import models
from kra.oom import is_critical_oom
from kra.utils import parse_cgroup

log = logging.getLogger(__name__)

MEBIBYTE = 1024 * 1024
target_message_re = re.compile(r'Kill\s+process\s+(\d+)\s+\((.*)\)')
victim_message_re = re.compile(r'Killed\s+process\s+(\d+)\s+\((.*)\)')
sys_victim_message_re = re.compile(r'victim\s+process:\s*(.*),\s+pid:\s*(\d+)')
retry_delay = 30


def main():
    install_shutdown_signal_handlers()

    q = queue.Queue()
    threads = SupervisedThreadGroup()
    threads.add_thread(WatcherThread(q))
    threads.add_thread(HandlerThread(q))
    threads.start_all()
    threads.wait_any()


class WatcherThread(SupervisedThread):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def run_supervised(self):
        v1 = kubernetes.client.CoreV1Api()
        watcher = iter(KubeWatcher(v1.list_event_for_all_namespaces))

        for event_type, event in watcher:
            if event_type == WatchEventType.DONE_INITIAL:
                break

        for event_type, event in watcher:
            if event_type != WatchEventType.ADDED:
                continue
            if event.reason != 'NodeOOM':
                continue
            self.queue.put(event)


class HandlerThread(SupervisedThread):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def run_supervised(self):
        while True:
            event = self.queue.get()
            fix_long_connections()
            try:
                self.handle(event)
            except Exception:
                log.exception('Failed to handle %s', event.metadata.name)

    def handle(self, event):
        try:
            self._handle(event)
        except models.Container.DoesNotExist as err:
            if getattr(event, '_retry', None):
                raise err
            log.info('Container not found, will retry in %s seconds', retry_delay)
            event._retry = True
            threading.Timer(retry_delay, lambda: self.queue.put(event)).start()

    def _handle(self, event):
        log.info('Event: %s', event.metadata.name)
        cgroup, comm, pid = parse_event_message(event.message)
        log.info('node: %s, cgroup: %s, comm: %s, pid: %s', event.involved_object.name, cgroup, comm, pid)
        if not cgroup:
            raise Exception(f'No cgroup in message "{event.message}"')
        container = get_container(cgroup)

        # Serialize with the pod collector: either it sees this event or this
        # handler sees its persisted termination evidence, regardless of order.
        with transaction.atomic():
            container = models.Container.objects.select_for_update().get(pk=container.pk)
            models.OOMEvent.objects.create(
                happened_at=event.last_timestamp,
                container=container,
                victim_comm=(comm or ''),
                victim_pid=pid,
                is_critical=is_critical_oom(container, event.last_timestamp),
            )
        log.info(f'OOM: {container.pod.namespace}/{container.pod.name}, container: {container.name}, comm: {comm}')


def get_container(cgroup):
    pod_uid, container_runtime_id = parse_cgroup(cgroup)
    log.info('pod_uid: %s, runtime_id: %s', pod_uid, container_runtime_id)
    if pod_uid is None or container_runtime_id is None:
        raise Exception(f'Unknown cgroup format "{cgroup}"')
    return models.Container.objects.get(runtime_id=container_runtime_id, pod__uid=pod_uid)


def parse_event_message(message):
    cgroup = None
    comm = None
    pid = None
    for line in message.split('\n'):
        key, value = line.split(':', maxsplit=1)
        if key == 'taskcg':
            cgroup = value
        elif key == 'proc':
            comm = value
        elif key == 'pid':
            pid = int(value)
    return cgroup, comm, pid


if __name__ == '__main__':
    main()
