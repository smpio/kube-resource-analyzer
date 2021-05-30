import time
import logging
from datetime import timedelta
from collections import defaultdict

import kubernetes
import kubernetes.client.rest
from django.utils import timezone
from prometheus_client.parser import text_string_to_metric_families

from utils.threading import SupervisedThread, SupervisedThreadGroup
from utils.kubernetes.watch import KubeWatcher
from utils.signal import install_shutdown_signal_handlers
from utils.django.db import fix_long_connections

from kra import models, kube_config
from kra.utils import parse_cgroup

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

        metrics = {family.name: family for family in text_string_to_metric_families(self.scrap_node(node))}
        squashed_metrics = defaultdict(dict)
        self.squash(metrics, 'container_memory_working_set_bytes', squashed_metrics)
        self.squash(metrics, 'container_cpu_usage_seconds', squashed_metrics)

        for (pod_uid, container_runtime_id), container_metrics in squashed_metrics.items():
            try:
                self.collect_container(pod_uid, container_runtime_id, container_metrics)
            except Exception:
                log.exception('Failed to collect pod')

    def scrap_node(self, node):
        client = kubernetes.client.ApiClient()
        response = client.call_api(
            '/api/v1/nodes/{node}/proxy/metrics/cadvisor', 'GET',
            path_params={
                'node': node.metadata.name,
            },
            auth_settings=['BearerToken'],
            response_type='object'
        )
        return response[0]

    def squash(self, metrics, metric_name, data):
        for sample in metrics[metric_name].samples:
            container_name = sample.labels['container']
            if not container_name or container_name == 'POD':
                continue

            cgroup = sample.labels['id']
            pod_uid, container_runtime_id = parse_cgroup(cgroup)
            if not pod_uid:
                continue
            if '-' not in pod_uid:
                # skip pods started directly by kubelet
                continue

            data[pod_uid, container_runtime_id][metric_name] = sample.value
            # use our own timestamp, because their timestamp differs for each metric
            # data[pod_uid, container_runtime_id]['timestamp'] = sample.timestamp

    def collect_container(self, pod_uid, runtime_id, container_metrics):
        try:
            container = models.Container.objects.get(pod__uid=pod_uid, runtime_id=runtime_id)
        except models.Container.DoesNotExist:
            log.debug('Container %s not found for pod %s', runtime_id, pod_uid)
            return

        usage = models.ResourceUsage(container=container)
        # See
        # https://stackoverflow.com/questions/65428558/what-is-the-difference-between-container-memory-working-set-bytes-and-contain
        # https://stackoverflow.com/questions/66832316/what-is-the-relation-between-container-memory-working-set-bytes-metric-and-oom
        usage.memory_mi = container_metrics['container_memory_working_set_bytes'] / MEBIBYTE + 1
        usage.cpu_m_seconds = container_metrics['container_cpu_usage_seconds'] * 1000
        usage.save()
