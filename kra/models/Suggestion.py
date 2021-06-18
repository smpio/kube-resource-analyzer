from django.db import models


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
