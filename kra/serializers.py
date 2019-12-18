from rest_framework import serializers

from utils.django.serializers.fields import ChoiceDisplayField

from . import models


class WorkloadSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Workload
        fields = '__all__'
    serializer_choice_field = ChoiceDisplayField


class PodSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Pod
        fields = '__all__'


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Container
        fields = '__all__'


class ResourceUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ResourceUsage
        fields = '__all__'


class OOMEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.OOMEvent
        fields = '__all__'


class AdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Adjustment
        fields = '__all__'
