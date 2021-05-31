import logging
from collections import defaultdict

from django.conf import settings
from django.db.models import F

from utils.django.db import bulk_save

from kra import models

log = logging.getLogger(__name__)


def make_suggestions():
    memory_reserve_multiplier = 1 + settings.BASE_MEMORY_RESERVE_FRACTION
    cpu_overuse_multiplier = 1 + settings.BASE_CPU_OVERUSE_FRACTION

    suggestions = models.Suggestion.objects.in_bulk(field_name='summary_id')

    oom_events = defaultdict(list)
    oom_qs = models.OOMEvent.objects.all() \
        .prefetch_related('container') \
        .annotate(workload_id=F('container__pod__workload_id')) \
        .order_by('happened_at')
    for e in oom_qs:
        oom_events[(e.workload_id, e.container.name)].append(e)

    max_memory_mi = 0
    max_cpu_m = 0
    summaries = list(models.Summary.objects.all())
    for stat in summaries:
        max_memory_mi = max(max_memory_mi, stat.max_memory_mi)
        if stat.memory_limit_mi:
            max_memory_mi = max(max_memory_mi, stat.memory_limit_mi)
        max_cpu_m = max(max_cpu_m, stat.avg_cpu_m)
        if stat.cpu_request_m:
            max_cpu_m = max(max_cpu_m, stat.cpu_request_m)

    with bulk_save() as save:
        for stat in summaries:
            try:
                sug = suggestions[stat.id]
            except KeyError:
                sug = models.Suggestion(summary=stat)

            memory_reasons = []
            cpu_reasons = []
            priorities = []
            new_memory_limits_mi = []
            new_cpu_requests_m = []

            pp = percent_priority

            container_oom_events = oom_events[(stat.workload_id, stat.container_name)]
            if container_oom_events:
                oom = container_oom_events[-1]
                if oom.container.memory_limit_mi and stat.memory_limit_mi:
                    min_memory_limit = int(oom.container.memory_limit_mi * memory_reserve_multiplier) + 1
                    if stat.memory_limit_mi < min_memory_limit:
                        new_memory_limits_mi.append(min_memory_limit)
                        priorities.append(200 + pp(min_memory_limit / max_memory_mi))
                        memory_reasons.append(f'OOM @ {oom.container.memory_limit_mi} Mi limit')

            min_memory_limit = int(stat.max_memory_mi * memory_reserve_multiplier) + 1
            if stat.memory_limit_mi:
                if stat.memory_limit_mi < min_memory_limit:
                    new_memory_limits_mi.append(min_memory_limit)
                    priorities.append(pp(min_memory_limit / max_memory_mi))
                    memory_reasons.append(f'memory usage {stat.max_memory_mi} Mi near limit {stat.memory_limit_mi} Mi')
            else:
                new_memory_limits_mi.append(min_memory_limit)
                priorities.append(1)

            if stat.cpu_request_m:
                max_cpu_usage = stat.cpu_request_m * cpu_overuse_multiplier
                if stat.avg_cpu_m > max_cpu_usage:
                    new_cpu_requests_m.append(stat.avg_cpu_m)
                    priorities.append(pp(stat.avg_cpu_m / max_cpu_m))
                    cpu_reasons.append(f'avg cpu usage {stat.avg_cpu_m}m exceeds request {stat.cpu_request_m}m too much')
            else:
                new_cpu_requests_m.append(stat.avg_cpu_m)
                priorities.append(1)

            if not priorities:
                if sug.id:
                    sug.delete()
                continue

            sug.memory_reason = '; '.join(memory_reasons)
            sug.cpu_reason = '; '.join(cpu_reasons)
            sug.priority = sum(priorities)

            if new_memory_limits_mi:
                sug.new_memory_limit_mi = max(new_memory_limits_mi)
            else:
                sug.new_memory_limit_mi = None

            if new_cpu_requests_m:
                sug.new_cpu_request_m = max(new_cpu_requests_m)
            else:
                sug.new_cpu_request_m = None

            save(sug)


def percent_priority(ratio):
    if ratio > 1:
        ratio = 1
    return ratio * 100
