from django.db import models


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
