import re
import queue
import logging

import kubernetes
import kubernetes.client.rest

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import fix_long_connections

from kra import models
from kra.utils import parse_cgroup

log = logging.getLogger(__name__)

MEBIBYTE = 1024 * 1024
target_message_re = re.compile(r'Kill\s+process\s+(\d+)\s+\((.*)\)')
victim_message_re = re.compile(r'Killed\s+process\s+(\d+)\s+\((.*)\)')


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
            if event.reason != 'OOMKilling':
                continue
            if event.involved_object.kind != 'Node':
                continue
            self.queue.put(event)


class HandlerThread(SupervisedThread):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def run_supervised(self):
        while True:
            event = self.queue.get()
            try:
                self.handle(event)
            except Exception:
                log.exception('Failed to handle event on node %s', event.involved_object.name)

    def handle(self, event):
        fix_long_connections()

        node = event.involved_object.name
        oom = models.OOMEvent(happened_at=event.last_timestamp)

        match = victim_message_re.search(event.message)
        if not match:
            raise Exception(f'No victim PID in message "{event.message}"')
        victim_pid, oom.victim_comm = int(match.group(1)), match.group(2)

        match = target_message_re.search(event.message)
        if not match:
            raise Exception(f'No target PID in message "{event.message}"')
        target_pid, oom.target_comm = int(match.group(1)), match.group(2)

        target_ps_record = get_ps_record(event, target_pid)
        if target_ps_record is not None:
            oom.target_pid = target_ps_record.nspid

        if victim_pid == target_pid:
            victim_ps_record = target_ps_record
        else:
            victim_ps_record = get_ps_record(event, victim_pid)
        if victim_ps_record is not None:
            oom.victim_pid = victim_ps_record.nspid

        ps_record = target_ps_record or victim_ps_record
        if ps_record is None:
            raise Exception(f'No ps records for node {node} and PIDs {target_pid}, {victim_pid}')

        pod_uid, container_runtime_id = parse_cgroup(ps_record.cgroup)
        if pod_uid is None or container_runtime_id is None:
            raise Exception(f'Unknown cgroup format "{ps_record.cgroup}"')

        oom.container = models.Container.objects.get(runtime_id=container_runtime_id, pod__uid=pod_uid)
        if oom.container is None:
            raise Exception(f'No container {container_runtime_id} in pod {pod_uid}')

        oom.save()
        log.info(f'OOM in {oom.container.pod.namespace}/{oom.container.pod.name}, container: {oom.container.name}, '
                 f'target: {oom.target_pid} ({oom.target_comm}), victim: {oom.victim_pid} ({oom.victim_comm})')


def get_ps_record(event, pid):
    node = event.involved_object.name
    return models.PSRecord.objects.filter(hostname=node, pid=pid, ts__lte=event.last_timestamp).order_by('-ts').first()



if __name__ == '__main__':
    main()
