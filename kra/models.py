import enum

from django.db import models
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
    priority = models.FloatField(validators=[MinValueValidator(0)], default=1)
    auto_downgrade = models.BooleanField(default=False)
    min_auto_downgrade_interval_sec = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = ('kind', 'namespace', 'name')


class Pod(models.Model):
    uid = models.UUIDField(unique=True)
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE, blank=True, null=True)
    namespace = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    spec_hash = models.CharField(max_length=32)  # maybe add WorkloadRevision proxy model
    started_at = models.DateTimeField()
    gone_at = models.DateTimeField(blank=True, null=True)


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


class ResourceUsage(models.Model):
    container = models.ForeignKey('Container', on_delete=models.CASCADE)
    measured_at = models.DateTimeField(default=timezone.now)
    memory_mi = models.PositiveIntegerField(blank=True, null=True)
    cpu_m = models.PositiveIntegerField(blank=True, null=True)
    cpu_m_seconds = models.BigIntegerField(blank=True, null=True)


class OOMEvent(models.Model):
    container = models.ForeignKey('Container', on_delete=models.CASCADE)
    happened_at = models.DateTimeField()
    target_pid = models.BigIntegerField(blank=True, null=True)
    victim_pid = models.BigIntegerField(blank=True, null=True)
    target_comm = models.CharField(max_length=32, blank=True)
    victim_comm = models.CharField(max_length=32, blank=True)


# maybe add resource kind enum
class Adjustment(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    done_at = models.DateTimeField()
    pre_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    new_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    pre_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)
    new_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)


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
