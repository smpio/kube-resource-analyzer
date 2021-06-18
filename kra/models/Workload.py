import enum
import itertools
from collections import defaultdict

from django.db import models
from django.core.validators import MinValueValidator

from utils.django.models import EnumField


class WorkloadKind(enum.IntEnum):
    ReplicaSet = 1
    Deployment = 2
    DaemonSet = 3
    CronJob = 4
    StatefulSet = 5
    Job = 6


class WorkloadManager(models.Manager):
    def get_queryset(self):
        return WorkloadQuerySet(self.model, using=self._db)


class Workload(models.Model):
    kind = EnumField(enum_class=WorkloadKind)
    namespace = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    affinity = models.JSONField(blank=True, null=True)

    # UNUSED
    priority = models.FloatField(validators=[MinValueValidator(0)], default=1)
    auto_downgrade = models.BooleanField(default=False)
    min_auto_downgrade_interval_sec = models.PositiveIntegerField(blank=True, null=True)

    objects = WorkloadManager()

    class Meta:
        unique_together = ('kind', 'namespace', 'name')

    def __str__(self):
        return f'{self.kind.name} {self.namespace}/{self.name}'


class WorkloadQuerySet(models.QuerySet):
    def _fetch_all(self):
        from kra.models import ResourceUsage
        super()._fetch_all()
        step = self._hints.get('_prefetch_resource_usage_buckets_step', None)
        if step is None:
            return

        workloads = self._result_cache
        container_ids = \
            itertools.chain.from_iterable(
                itertools.chain.from_iterable(
                    (c.id for c in pod.container_set.all()) for pod in wl.pod_set.all()
                ) for wl in workloads
            )
        qs = ResourceUsage.objects.filter(container_id__in=container_ids)\
            .annotate(
                ts=models.Func(
                    models.Value(f'{step} seconds'), 'measured_at',
                    function='time_bucket',
                    output_field=models.DateTimeField()
                ),
            )\
            .values('container_id', 'ts')\
            .order_by('container_id', 'ts')\
            .annotate(
                memory_mi=models.Max('memory_mi'),
                cpu_m_seconds=models.Max('cpu_m_seconds'),
            )

        buckets_by_container_id = defaultdict(list)
        for b in qs:
            buckets_by_container_id[b.pop('container_id')].append(b)

        for wl in workloads:
            for pod in wl.pod_set.all():
                for c in pod.container_set.all():
                    c.resource_usage_buckets = buckets_by_container_id[c.id]

    def prefetch_resource_usage_buckets(self, step):
        clone = self._chain()
        clone._hints['_prefetch_resource_usage_buckets_step'] = step
        return clone
