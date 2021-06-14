import os
import pickle
import logging
from collections import defaultdict

from utils.django.db import bulk_save

from kra import models
from kra.analytics.container import get_containers_summary
from .make_summary import _fill_summary

log = logging.getLogger(__name__)


def make_summaries():
    containers_by_pod_id = None

    summary_dump_filename = os.environ.get('KRA_INTERMEDIATE_DUMP')
    if summary_dump_filename:
        try:
            with open(summary_dump_filename, 'rb') as summary_dump_file:
                containers_by_pod_id = pickle.load(summary_dump_file)
        except Exception:
            log.exception('Failed to load summary dump')

    if containers_by_pod_id is None:
        log.info('Query containers summary...')
        containers_by_pod_id = defaultdict(list)
        for c in get_containers_summary():
            containers_by_pod_id[c.pod_id].append(c)
        if summary_dump_filename:
            with open(summary_dump_filename, 'wb') as summary_dump_file:
                pickle.dump(containers_by_pod_id, summary_dump_file)

    log.info('Collecting results')

    pods_by_workload_id = defaultdict(list)
    for pod in models.Pod.objects.all():
        pods_by_workload_id[pod.workload_id].append(pod)

    models.Summary.objects.all().delete()

    with bulk_save() as save:
        for wl in models.Workload.objects.all().order_by('namespace', 'name'):
            containers_by_name = defaultdict(list)
            for pod in pods_by_workload_id[wl.id]:
                for c in containers_by_pod_id[pod.id]:
                    containers_by_name[c.name].append(c)
            for container_name, containers in containers_by_name.items():
                summary = models.Summary(workload=wl, container_name=container_name)
                save(summary)
                for instance_summary in _fill_summary(summary, containers):
                    save(instance_summary)
