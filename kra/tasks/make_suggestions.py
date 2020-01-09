import logging

from django.conf import settings
from django.db import transaction

from kra import models

log = logging.getLogger(__name__)


def make_suggestions(force_update=False, force_summary_update=False):
    for stat in models.Summary.get_all(force_summary_update):
        with transaction.atomic():
            make_suggestion(stat, force_update)


def make_suggestion(stat, force_update=False):
    memory_reserve_multiplier = 1 + settings.BASE_MEMORY_RESERVE_FRACTION

    try:
        sug = models.Suggestion.objects.get(summary=stat)
        if not force_update:
            return
    except models.Suggestion.DoesNotExist:
        sug = models.Suggestion(summary=stat)

    reasons = []
    priorities = []
    new_memory_limits_mi = []
    new_cpu_requests_m = []

    oom = models.OOMEvent.objects.filter(container__pod__workload=stat.workload,
                                         container__name=stat.container_name).order_by('happened_at').last()
    if oom and oom.container.memory_limit_mi:
        min_memory_limit = int(oom.container.memory_limit_mi * memory_reserve_multiplier) + 1
        if stat.memory_limit_mi < min_memory_limit:
            new_memory_limits_mi.append(min_memory_limit)
            priorities.append(1000 + ((min_memory_limit / stat.memory_limit_mi) - 1) * 100)
            reasons.append(f'OOM @ {oom.container.memory_limit_mi} Mi limit')

    sug.reason = '; '.join(reasons)

    if priorities:
        sug.priority = max(priorities)
    else:
        sug.priority = 0

    if new_memory_limits_mi:
        sug.new_memory_limit_mi = max(new_memory_limits_mi)
    else:
        sug.new_memory_limit_mi = None

    if new_cpu_requests_m:
        sug.new_cpu_request_m = max(new_cpu_requests_m)
    else:
        sug.new_cpu_request_m = None

    sug.save()
