from django.db import models


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
