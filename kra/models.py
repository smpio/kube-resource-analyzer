import enum

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator

from utils.django.models import EnumField


class WorkloadKind(enum.IntEnum):
    ReplicaSet = 1
    Deployment = 2
    DaemonSet = 3
    CronJob = 4
    StatefulSet = 5
    Job = 6


class Workload(models.Model):
    kind = EnumField(enum_class=WorkloadKind)
    namespace = models.CharField(max_length=255)
    name = models.CharField(max_length=255)

    # UNUSED
    priority = models.FloatField(validators=[MinValueValidator(0)], default=1)
    auto_downgrade = models.BooleanField(default=False)
    min_auto_downgrade_interval_sec = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = ('kind', 'namespace', 'name')

    def __str__(self):
        return f'{self.kind.name} {self.namespace}/{self.name}'


class Pod(models.Model):
    uid = models.UUIDField(unique=True)
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE, blank=True, null=True)
    namespace = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    spec_hash = models.CharField(max_length=32)  # maybe add WorkloadRevision proxy model
    started_at = models.DateTimeField()
    gone_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f'{self.namespace}/{self.name}'


class Container(models.Model):
    pod = models.ForeignKey('Pod', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    runtime_id = models.CharField(max_length=255)
    memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = [
            ('pod', 'name'),
            ('pod', 'runtime_id'),
        ]

    def __str__(self):
        return f'{self.pod} {self.name}'


class ResourceUsage(models.Model):
    container = models.ForeignKey('Container', on_delete=models.CASCADE)
    measured_at = models.DateTimeField(default=timezone.now)
    memory_mi = models.PositiveIntegerField(blank=True, null=True)
    cpu_m = models.PositiveIntegerField(blank=True, null=True)  # TODO: remove
    cpu_m_seconds = models.BigIntegerField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['measured_at']),
        ]


class OOMEvent(models.Model):
    container = models.ForeignKey('Container', on_delete=models.CASCADE)
    happened_at = models.DateTimeField()
    target_pid = models.BigIntegerField(blank=True, null=True)
    victim_pid = models.BigIntegerField(blank=True, null=True)
    target_comm = models.CharField(max_length=32, blank=True)
    victim_comm = models.CharField(max_length=32, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['happened_at']),
        ]


# maybe add resource kind enum
class Adjustment(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    done_at = models.DateTimeField()
    pre_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    new_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    pre_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)
    new_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['done_at']),
        ]


class Summary(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    container_name = models.CharField(max_length=255)
    done_at = models.DateTimeField(auto_now=True)

    max_memory_mi = models.PositiveIntegerField(blank=True, null=True)
    memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)

    avg_cpu_m = models.PositiveIntegerField(blank=True, null=True)
    cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = ('workload', 'container_name')

    @staticmethod
    def get_all(force_update=False):
        from kra.tasks import make_summary

        if not force_update:
            max_age = settings.MAX_SUMMARY_AGE
            last_summary = Summary.objects.order_by('done_at').last()
            if last_summary is None:
                force_update = True
            else:
                force_update = timezone.now() - last_summary.done_at > max_age

        if force_update:
            yield from make_summary()
        else:
            yield from Summary.objects\
                .order_by('workload__namespace', 'workload__name')\
                .select_related('workload')


class Suggestion(models.Model):
    summary = models.OneToOneField('Summary', on_delete=models.CASCADE)
    done_at = models.DateTimeField(auto_now=True)

    new_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    new_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    reason = models.TextField(blank=True)
    priority = models.IntegerField(default=0)

    @staticmethod
    def get_all(force_update=False):
        from kra.tasks import make_suggestions
        if force_update:
            make_suggestions(force_update=force_update)
        return Suggestion.objects.order_by('-priority')


class PSRecord(models.Model):
    """External database model"""

    ts = models.DateTimeField(primary_key=True)
    hostname = models.TextField()
    pid = models.BigIntegerField()
    cgroup = models.TextField()
    nspid = models.BigIntegerField()

    class Meta:
        db_table = 'records'
        managed = False
