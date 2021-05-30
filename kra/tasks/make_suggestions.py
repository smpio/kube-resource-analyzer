import logging
from collections import defaultdict

from django.conf import settings
from django.db.models import F

from utils.django.db import bulk_save

from kra import models

log = logging.getLogger(__name__)


def make_suggestions():
    memory_reserve_multiplier = 1 + settings.BASE_MEMORY_RESERVE_FRACTION

    suggestions = models.Suggestion.objects.in_bulk(field_name='summary_id')

    oom_events = defaultdict(list)
    oom_qs = models.OOMEvent.objects.all() \
        .prefetch_related('container') \
        .annotate(workload_id=F('container__pod__workload_id')) \
        .order_by('happened_at')
    for e in oom_qs:
        oom_events[(e.workload_id, e.container.name)].append(e)

    with bulk_save() as save:
        for stat in models.Summary.objects.all():
            try:
                sug = suggestions[stat.id]
            except KeyError:
                sug = models.Suggestion(summary=stat)

            reasons = []
            priorities = []
            new_memory_limits_mi = []
            new_cpu_requests_m = []

            container_oom_events = oom_events[(stat.workload_id, stat.container_name)]
            if container_oom_events:
                oom = container_oom_events[-1]
                if oom.container.memory_limit_mi and stat.memory_limit_mi:
                    min_memory_limit = int(oom.container.memory_limit_mi * memory_reserve_multiplier) + 1
                    if stat.memory_limit_mi < min_memory_limit:
                        new_memory_limits_mi.append(min_memory_limit)
                        priorities.append(1000 + ((min_memory_limit / stat.memory_limit_mi) - 1) * 100)
                        reasons.append(f'OOM @ {oom.container.memory_limit_mi} Mi limit')

            if stat.memory_limit_mi:
                min_memory_limit = int(stat.max_memory_mi * memory_reserve_multiplier) + 1
                if stat.memory_limit_mi < min_memory_limit:
                    new_memory_limits_mi.append(min_memory_limit)
                    priorities.append(1000 + ((min_memory_limit / stat.memory_limit_mi) - 1) * 100)
                    reasons.append(f'Recorded memory usage {stat.max_memory_mi} Mi')

            if not priorities:
                if sug.id:
                    sug.delete()
                continue

            sug.reason = '; '.join(reasons)
            sug.priority = max(priorities)

            if new_memory_limits_mi:
                sug.new_memory_limit_mi = max(new_memory_limits_mi)
            else:
                sug.new_memory_limit_mi = None

            if new_cpu_requests_m:
                sug.new_cpu_request_m = max(new_cpu_requests_m)
            else:
                sug.new_cpu_request_m = None

            save(sug)
