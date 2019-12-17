import time
import logging
from datetime import timedelta

import kubernetes
import kubernetes.client.rest
from django.utils import timezone

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher
from utils.signal import install_shutdown_signal_handlers

from kra import models, kube_config

log = logging.getLogger(__name__)


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
            self.collect()
            end = timezone.now()
            elapsed = end - start
            to_wait = self.collect_interval - elapsed
            to_wait_seconds = to_wait.total_seconds()
            if to_wait_seconds > 0:
                log.info('Waiting %d seconds for next collect cycle', to_wait_seconds)
                time.sleep(to_wait_seconds)

    def collect(self):
        for node in self.node_db.values():
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
        response = client.call_api('/api/v1/nodes/{node}/proxy/stats/summary', 'GET', path_params={
            'node': node.metadata.name,
        }, response_type='object')
        return response[0]

    def collect_pod(self, pod_metrics):
        pod_uid = pod_metrics['podRef']['uid']

        if pod_uid == '61e7f480b84eb873be0eabec2e213ae6':
            # this is strange pod uid used for for all kube-proxy pods in stats
            return

        containers = {c.name: c for c in models.Container.objects.filter(pod__uid=pod_uid)}
        for container_metrics in pod_metrics['containers']:
            container = containers.get(container_metrics['name'])
            if not container:
                log.debug('Container %s not found for pod %s', container_metrics['name'], pod_uid)
                continue
            usage = models.ResourceUsage(container=container)
            usage.memory_mi = container_metrics['memory']['workingSetBytes'] / 1024 / 1024 + 1
            # TODO: use usageCoreNanoSeconds and compare with prev value
            usage.cpu_m = container_metrics['cpu']['usageNanoCores'] / 1000
            usage.save()
