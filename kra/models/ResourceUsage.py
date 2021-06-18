from django.db import models
from django.utils import timezone


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
