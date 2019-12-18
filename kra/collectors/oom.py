import re
import queue
import logging

import kubernetes
import kubernetes.client.rest

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher, WatchEventType
from utils.signal import install_shutdown_signal_handlers

from kra import models, kube_config

log = logging.getLogger(__name__)

MEBIBYTE = 1024 * 1024
target_message_re = re.compile(r'Kill\s+process\s+(\d+)\s+\((.*)\)')
victim_message_re = re.compile(r'Killed\s+process\s+(\d+)\s+\((.*)\)')
cgroup_re = re.compile(r'/pod([\w\-]+)/(\w+)$')


def main():
    install_shutdown_signal_handlers()
    kube_config.init()

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
        node = event.involved_object.name
        oom = models.OOMEvent(happened_at=event.last_timestamp)

        match = victim_message_re.search(event.message)
        if not match:
            raise Exception(f'No victim PID in message "{event.message}"')
        oom.victim_pid, oom.victim_comm = int(match.group(1)), match.group(2)

        match = target_message_re.search(event.message)
        if not match:
            raise Exception(f'No target PID in message "{event.message}"')
        oom.target_pid, oom.target_comm = int(match.group(1)), match.group(2)

        ps_record = get_ps_record(event, oom.target_pid)
        if ps_record is None:
            raise Exception(f'No ps record for node {node} and PID {oom.target_pid}')

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


def parse_cgroup(cgroup):
    match = cgroup_re.search(cgroup)
    if not match:
        return None, None
    return match.group(1), match.group(2)


if __name__ == '__main__':
    main()
