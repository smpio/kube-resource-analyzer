from rest_framework import viewsets

from kra import models
from kra import serializers


class WorkloadViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.WorkloadSerializer
    queryset = models.Workload.objects.all()


class PodViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.PodSerializer
    queryset = models.Pod.objects.all()


class ContainerViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.ContainerSerializer
    queryset = models.Container.objects.all()


class ResourceUsageViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.ResourceUsageSerializer
    queryset = models.ResourceUsage.objects.all()


class OOMEventViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.OOMEventSerializer
    queryset = models.OOMEvent.objects.all()


class AdjustmentViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.AdjustmentSerializer
    queryset = models.Adjustment.objects.all()
