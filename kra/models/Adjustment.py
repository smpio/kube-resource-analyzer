from django.db import models


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
