from django.db import models


class OOMEvent(models.Model):
    container = models.ForeignKey('Container', on_delete=models.CASCADE)
    happened_at = models.DateTimeField()
    target_pid = models.BigIntegerField(blank=True, null=True)
    victim_pid = models.BigIntegerField(blank=True, null=True)
    target_comm = models.CharField(max_length=32, blank=True)
    victim_comm = models.CharField(max_length=32, blank=True)
    is_critical = models.BooleanField()  # whether whole container was stopped or not
    is_ignored = models.BooleanField(default=False)  # whether to ignore this in suggestions

    class Meta:
        indexes = [
            models.Index(fields=['happened_at']),
        ]

    def __str__(self):
        return str(self.happened_at)
