import logging
from collections import defaultdict

from django.db.models import F

from utils.django.db import bulk_save

from kra import models
from kra.celery import task
from .make_suggestion import _make_suggestion

log = logging.getLogger(__name__)


@task
def make_suggestions():
    oom_events = defaultdict(list)
    oom_qs = models.OOMEvent.objects.all() \
        .prefetch_related('container') \
        .annotate(workload_id=F('container__pod__workload_id'))
    for e in oom_qs:
        oom_events[(e.workload_id, e.container.name)].append(e)

    with bulk_save() as save:
        for stat in models.Summary.objects.select_related('suggestion'):
            sug = _make_suggestion(stat, oom_events[(stat.workload_id, stat.container_name)])
            if sug:
                save(sug)
