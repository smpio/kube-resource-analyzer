from django.db import models


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
