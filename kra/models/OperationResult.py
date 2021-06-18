from django.db import models


class OperationResult(models.Model):
    finished_at = models.DateTimeField()
    data = models.JSONField(blank=True, null=True)
    error = models.JSONField(blank=True, null=True)

    def __str__(self):
        return str(self.data or 'OK')
