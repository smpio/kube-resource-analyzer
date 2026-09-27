from django.db import models
from django.db.models import Q


class Adjustment(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    scheduled_for = models.DateTimeField()
    result = models.ForeignKey('OperationResult', on_delete=models.PROTECT, blank=True, null=True)
    resource_version = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['scheduled_for']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workload'],
                condition=Q(result__isnull=True),
                name='kra_one_active_adjustment_per_workload',
            ),
        ]

    def __str__(self):
        return f'{self.workload} - {self.result or self.scheduled_for}'
