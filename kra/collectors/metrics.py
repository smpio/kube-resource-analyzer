import time
import logging
import datetime
from datetime import timedelta

import kubernetes
import kubernetes.client.rest
from django.utils import timezone

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import fix_long_connections

from kra import models, kube_config

log = logging.getLogger(__name__)

MEBIBYTE = 1024 * 1024


def main():
    install_shutdown_signal_handlers()
    kube_config.init()

    v1 = kubernetes.client.CoreV1Api()
    watcher = KubeWatcher(v1.list_node)

    threads = SupervisedThreadGroup()
    threads.add_thread(WatcherThread(watcher))
    threads.add_thread(CollectorThread(watcher.db))
    threads.start_all()
    threads.wait_any()


class WatcherThread(SupervisedThread):
    def __init__(self, watcher):
        super().__init__()
        self.watcher = watcher

    def run_supervised(self):
        for _ in self.watcher:
            pass


class CollectorThread(SupervisedThread):
    def __init__(self, node_db, collect_interval=timedelta(minutes=1)):
        super().__init__()
        self.node_db = node_db
        self.collect_interval = collect_interval

    def run_supervised(self):
        while True:
            start = timezone.now()
            fix_long_connections()
            self.collect()
            end = timezone.now()
            elapsed = end - start
            to_wait = self.collect_interval - elapsed
            to_wait_seconds = to_wait.total_seconds()
            if to_wait_seconds > 0:
                log.info('Waiting %d seconds for next collect cycle', to_wait_seconds)
                time.sleep(to_wait_seconds)

    def collect(self):
        nodes = list(self.node_db.values())
        for node in nodes:
            try:
                self.collect_node(node)
            except Exception:
                log.exception('Failed to collect node')

    def collect_node(self, node):
        log.info('Collecting node %s', node.metadata.name)
        metrics = self.scrap_node(node)
        for pod_metrics in metrics['pods']:
            try:
                self.collect_pod(pod_metrics)
            except Exception:
                log.exception('Failed to collect pod')

    def scrap_node(self, node):
        client = kubernetes.client.ApiClient()
        response = client.call_api(
            '/api/v1/nodes/{node}/proxy/stats/summary', 'GET',
            path_params={
                'node': node.metadata.name,
            },
            auth_settings=['BearerToken'],
            response_type='object'
        )
        return response[0]

    def collect_pod(self, pod_metrics):
        pod_uid = pod_metrics['podRef']['uid']

        if not pod_metrics.get('containers'):
            log.info('No container metrics for pod %(namespace)s/%(name)s', pod_metrics['podRef'])
            return

        if '-' not in pod_uid:
            # skip pods started directly by kubelet
            return

        containers = {c.name: c for c in models.Container.objects.filter(pod__uid=pod_uid)}
        for container_metrics in pod_metrics['containers']:
            container = containers.get(container_metrics['name'])
            if not container:
                log.debug('Container %s not found for pod %s', container_metrics['name'], pod_uid)
                continue

            usage = models.ResourceUsage(container=container)
            iso_timestamp = container_metrics['memory']['time'].replace('Z', '+00:00')
            usage.measured_at = datetime.datetime.fromisoformat(iso_timestamp)
            # See
            # https://stackoverflow.com/questions/65428558/what-is-the-difference-between-container-memory-working-set-bytes-and-contain
            # https://stackoverflow.com/questions/66832316/what-is-the-relation-between-container-memory-working-set-bytes-metric-and-oom
            usage.memory_mi = container_metrics['memory']['workingSetBytes'] / MEBIBYTE + 1
            usage.cpu_m_seconds = container_metrics['cpu']['usageCoreNanoSeconds'] / 1000000
            usage.save()
