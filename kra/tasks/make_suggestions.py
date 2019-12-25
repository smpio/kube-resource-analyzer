import logging

from django.conf import settings
from django.db import transaction

from kra import models

log = logging.getLogger(__name__)


@transaction.atomic
def make_suggestions(force_update_investigations=False):
    models.Suggestion.objects.all().delete()

    for stat in models.Investigation.get_all(force_update_investigations):
        memory_reserve_multiplier = 1 + settings.BASE_MEMORY_RESERVE_FRACTION

        oom = models.OOMEvent.objects.filter(container__pod__workload=stat.workload,
                                             container__name=stat.container_name).order_by('happened_at').last()
        if oom:
            min_memory_limit = int(oom.container.memory_limit_mi * memory_reserve_multiplier) + 1

            if stat.memory_limit_mi < min_memory_limit:
                sug = models.Suggestion(workload=stat.workload, container_name=stat.container_name)
                sug.new_memory_limit_mi = min_memory_limit
                sug.priority = 1000 + ((min_memory_limit / stat.memory_limit_mi) - 1) * 100
                sug.reason = f'OOM @ {oom.container.memory_limit_mi} Mi limit'
                sug.save()
