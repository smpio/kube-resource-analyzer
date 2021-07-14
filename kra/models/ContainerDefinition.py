from django.db import models

# не решит проблему, т.к. эти данные собираются только когда есть живые поды

class ContainerDefinition(models.Model):
    workload = models.ForeignKey('Workload', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    memory_limit_mi = models.PositiveIntegerField(blank=True, null=True)
    cpu_request_m = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        unique_together = [
            ('workload', 'name'),
        ]

    def __str__(self):
        return f'{self.workload} {self.name}'
