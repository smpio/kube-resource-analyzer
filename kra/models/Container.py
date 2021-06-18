from django.db import models


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
