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
    affinity = models.JSONField(blank=True, null=True)

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
    spec_hash = models.CharField(max_length=32)
    started_at = models.DateTimeField()
    gone_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['started_at']),
        ]

    def __str__(self):
        return f'{self.namespace}/{self.name}'


class Container(models.Model):
    pod = models.ForeignKey('Pod', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    runtime_id = models.CharField(max_length=255)
    started_at = models.DateTimeField()
    memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = [
            ('pod', 'runtime_id'),
        ]
        indexes = [
            models.Index(fields=['started_at']),
        ]

    def __str__(self):
        return f'{self.pod} {self.name}'


class ResourceUsage(models.Model):
    container = models.ForeignKey('Container', on_delete=models.CASCADE)
    measured_at = models.DateTimeField(default=timezone.now)
    memory_mi = models.PositiveIntegerField()
    cpu_m_seconds = models.BigIntegerField()

    class Meta:
        indexes = [
            models.Index(fields=['measured_at']),
            models.Index(fields=['container_id', 'measured_at']),
        ]

    def __str__(self):
        return f'{self.memory_mi} Mi, {self.cpu_m_seconds} m*sec'


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

    def __str__(self):
        return str(self.happened_at)


class Adjustment(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    scheduled_for = models.DateTimeField()
    result = models.ForeignKey('OperationResult', on_delete=models.PROTECT, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['scheduled_for']),
        ]

    def __str__(self):
        return f'{self.workload} - {self.result or self.scheduled_for}'


class ContainerAdjustment(models.Model):
    adjustment = models.ForeignKey('Adjustment', on_delete=models.CASCADE, related_name='containers')
    container_name = models.CharField(max_length=255)
    new_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    new_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)


class Summary(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    container_name = models.CharField(max_length=255)
    done_at = models.DateTimeField(auto_now=True)

    max_memory_mi = models.PositiveIntegerField()
    avg_memory_mi = models.PositiveIntegerField()
    stddev_memory_mi = models.PositiveIntegerField()
    memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)

    max_cpu_m = models.PositiveIntegerField()
    avg_cpu_m = models.PositiveIntegerField()
    stddev_cpu_m = models.PositiveIntegerField()
    cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = ('workload', 'container_name')

    def __str__(self):
        return f'{self.workload} {self.container_name}'


class InstanceSummary(models.Model):
    """
    Summary per single pod container
    """
    aggregated = models.ForeignKey('Summary', on_delete=models.CASCADE)

    # TODO: add since, till

    max_memory_mi = models.PositiveIntegerField()
    avg_memory_mi = models.PositiveIntegerField()
    stddev_memory_mi = models.PositiveIntegerField()

    max_cpu_m = models.PositiveIntegerField()
    avg_cpu_m = models.PositiveIntegerField()
    stddev_cpu_m = models.PositiveIntegerField()


class Suggestion(models.Model):
    summary = models.OneToOneField('Summary', on_delete=models.CASCADE)
    done_at = models.DateTimeField(auto_now=True)

    new_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    new_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    memory_reason = models.TextField(blank=True)
    cpu_reason = models.TextField(blank=True)

    priority = models.IntegerField(default=0)

    def __str__(self):
        return str(self.summary)


class OperationResult(models.Model):
    finished_at = models.DateTimeField()
    data = models.JSONField(blank=True, null=True)
    error = models.JSONField(blank=True, null=True)

    def __str__(self):
        return str(self.data or 'OK')


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
