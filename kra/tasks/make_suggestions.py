import logging
from collections import defaultdict

from django.conf import settings
from django.db.models import F

from utils.django.db import bulk_save

from kra import models

log = logging.getLogger(__name__)


def make_suggestions():
    oom_events = defaultdict(list)
    oom_qs = models.OOMEvent.objects.all() \
        .prefetch_related('container') \
        .annotate(workload_id=F('container__pod__workload_id')) \
        .order_by('happened_at')
    for e in oom_qs:
        oom_events[(e.workload_id, e.container.name)].append(e)

    with bulk_save() as save:
        for stat in models.Summary.objects.select_related('suggestion'):
            try:
                sug = stat.suggestion
            except models.Suggestion.DoesNotExist:
                sug = models.Suggestion(summary=stat)

            new_memory_limit_mi, memory_priority, memory_reason = \
                suggest_memory(stat, oom_events[(stat.workload_id, stat.container_name)])

            new_cpu_request_m, cpu_priority, cpu_reason = suggest_cpu(stat)

            if new_memory_limit_mi is None and new_cpu_request_m is None:
                if sug.id:
                    sug.delete()
                continue

            sug.memory_reason = memory_reason
            sug.cpu_reason = cpu_reason
            sug.priority = memory_priority + cpu_priority
            sug.new_memory_limit_mi = new_memory_limit_mi
            sug.new_cpu_request_m = new_cpu_request_m
            save(sug)


def suggest_memory(stat, oom_events):
    new_limit = None
    priority = 0
    reason = ''

    target_limit = round(stat.max_memory_mi * settings.MEM_TARGET_REQUEST)

    for oom in oom_events:
        if oom.container.memory_limit_mi:
            target_limit2 = round(oom.container.memory_limit_mi * settings.MEM_TARGET_REQUEST)
            if target_limit2 > target_limit:
                target_limit = target_limit2
                reason = f'OOM @ {oom.container.memory_limit_mi} Mi limit'

    lower_bound = round(target_limit * settings.MEM_BOUNDS[0])
    upper_bound = round(target_limit * settings.MEM_BOUNDS[1])

    if stat.memory_limit_mi:
        if stat.memory_limit_mi < lower_bound:
            new_limit = target_limit
            priority = target_limit - stat.memory_limit_mi
            if not reason:
                reason = f'memory limit {stat.memory_limit_mi} Mi < lower bound {lower_bound} Mi'
            else:
                priority *= 2
        elif stat.memory_limit_mi > upper_bound:
            new_limit = target_limit
            priority = stat.memory_limit_mi - target_limit
            reason = f'memory limit {stat.memory_limit_mi} Mi > upper bound {upper_bound} Mi'
    else:
        new_limit = target_limit
        priority = 1

    return new_limit, priority, reason


def suggest_cpu(stat):
    new_request = None
    priority = 0
    reason = ''

    target_limit = round(stat.avg_cpu_m * settings.CPU_TARGET_REQUEST)
    lower_bound = round(target_limit * settings.CPU_BOUNDS[0])
    upper_bound = round(target_limit * settings.CPU_BOUNDS[1])

    if stat.cpu_request_m:
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
        priority = 1

    return new_request, priority, reason
