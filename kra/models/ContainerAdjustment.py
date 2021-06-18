from django.db import models


class ContainerAdjustment(models.Model):
    adjustment = models.ForeignKey('Adjustment', on_delete=models.CASCADE, related_name='containers')
    container_name = models.CharField(max_length=255)
    new_memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    new_cpu_request_m = models.PositiveIntegerField(blank=True, null=True)
