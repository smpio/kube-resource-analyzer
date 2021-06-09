import math
import logging

from django.conf import settings

from kra import models
from kra.celery import task

log = logging.getLogger(__name__)


@task
def make_suggestion(workload_id, container_name):
    summary = models.Summary.objects\
        .select_related('suggestion')\
        .get(workload_id=workload_id, container_name=container_name)
    oom_events = models.OOMEvent.objects\
        .filter(container__pod__workload_id=workload_id, container__name=container_name)\
        .prefetch_related('container')
    sug = _make_suggestion(summary,oom_events)
    if sug:
        sug.save()


def _make_suggestion(stat, oom_events):
    try:
        sug = stat.suggestion
    except models.Suggestion.DoesNotExist:
        sug = models.Suggestion(summary=stat)

    new_memory_limit_mi, memory_priority, memory_reason = _suggest_memory(stat, oom_events)
    new_cpu_request_m, cpu_priority, cpu_reason = _suggest_cpu(stat)

    if new_memory_limit_mi is None and new_cpu_request_m is None:
        if sug.id:
            sug.delete()
        return None

    sug.memory_reason = memory_reason
    sug.cpu_reason = cpu_reason
    sug.priority = memory_priority + cpu_priority
    sug.new_memory_limit_mi = new_memory_limit_mi
    sug.new_cpu_request_m = new_cpu_request_m
    return sug


def _suggest_memory(stat, oom_events):
    new_limit = None
    priority = 0
    reason = ''
    oom = None

    target_limit = math.ceil(stat.max_memory_mi * settings.MEM_TARGET_REQUEST)

    for oom in oom_events:
        if oom.container.memory_limit_mi:
            target_limit2 = math.ceil(oom.container.memory_limit_mi * settings.MEM_TARGET_REQUEST)
            if target_limit2 > target_limit:
                target_limit = target_limit2
                priority = settings.OOM_PRIORITY
                reason = f'OOM @ {oom.happened_at}, {oom.container.memory_limit_mi} Mi limit'

    target_limit = max(target_limit, settings.MEM_MIN)
    lower_bound = math.ceil(target_limit * settings.MEM_BOUNDS[0])
    lower_bound = max(lower_bound, settings.MEM_MIN)
    upper_bound = math.ceil(target_limit * settings.MEM_BOUNDS[1])

    if stat.memory_limit_mi is not None:
        if stat.memory_limit_mi < lower_bound:
            new_limit = target_limit
            priority += target_limit - stat.memory_limit_mi
            if not reason:
                reason = f'memory limit {stat.memory_limit_mi} Mi < lower bound {lower_bound} Mi'
        elif stat.memory_limit_mi > upper_bound:
            new_limit = target_limit
            priority += stat.memory_limit_mi - target_limit
            reason = f'memory limit {stat.memory_limit_mi} Mi > upper bound {upper_bound} Mi'
    else:
        new_limit = target_limit
        priority = target_limit
        if oom:
            priority += settings.OOM_PRIORITY

    if new_limit is None:
        priority = 0
        reason = ''

    return new_limit, priority, reason


def _suggest_cpu(stat):
    new_request = None
    priority = 0
    reason = ''

    target_limit = round(stat.avg_cpu_m * settings.CPU_TARGET_REQUEST)
    lower_bound = round(target_limit * settings.CPU_BOUNDS[0])
    upper_bound = round(target_limit * settings.CPU_BOUNDS[1])

    if stat.cpu_request_m is not None:
        if stat.cpu_request_m < lower_bound:
            new_request = target_limit
            priority = target_limit - stat.cpu_request_m
            reason = f'cpu request {stat.cpu_request_m}m < lower bound {lower_bound}m'
        elif stat.cpu_request_m > upper_bound:
            new_request = target_limit
            priority = stat.cpu_request_m - target_limit
            reason = f'cpu request {stat.cpu_request_m}m > upper bound {lower_bound}m'
    else:
        new_request = target_limit
        priority = target_limit

    return new_request, priority, reason
