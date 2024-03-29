from rest_framework import serializers

from utils.django.serializers.fields import ChoiceDisplayField

from . import models


class NestedSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Suggestion
        fields = [
            'id',
            'done_at',
            'new_memory_limit_mi',
            'new_cpu_request_m',
            'memory_reason',
            'cpu_reason',
            'priority',
        ]


class NestedSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Summary
        fields = [
            'container_name',
            'done_at',
            'max_memory_mi',
            'avg_memory_mi',
            'stddev_memory_mi',
            'memory_limit_mi',
            'max_cpu_m',
            'avg_cpu_m',
            'stddev_cpu_m',
            'cpu_request_m',
            'suggestion',
        ]

    suggestion = NestedSuggestionSerializer(read_only=True)


class NestedContainerAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ContainerAdjustment
        fields = [
            'container_name',
            'new_memory_limit_mi',
            'new_cpu_request_m',
        ]


class OperationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.OperationResult
        fields = '__all__'


class AdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Adjustment
        fields = [
            'id',
            'workload',
            'scheduled_for',
            'result',
            'containers',
        ]

    result = OperationResultSerializer(read_only=True)
    containers = NestedContainerAdjustmentSerializer(many=True)

    def create(self, validated_data):
        containers_data = validated_data.pop('containers')
        instance = models.Adjustment.objects.create(**validated_data)
        models.ContainerAdjustment.objects.bulk_create(
            models.ContainerAdjustment(adjustment=instance, **d) for d in containers_data)
        return instance

    def update(self, instance, validated_data):
        containers_data = validated_data.pop('containers')
        models.ContainerAdjustment.objects.filter(adjustment=instance).delete()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        models.ContainerAdjustment.objects.bulk_create(
            models.ContainerAdjustment(adjustment=instance, **d) for d in containers_data)
        return instance


class OOMEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.OOMEvent
        fields = [
            'id',
            'happened_at',
            'is_critical',
            'is_ignored',
        ]


class ContainerSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Container
        fields = [
            'id',
            'name',
            'runtime_id',
            'started_at',
            'finished_at',
            'memory_limit_mi',
            'cpu_request_m',
            'oomevent_set',
            'resource_usage_buckets',
        ]

    oomevent_set = OOMEventSerializer(many=True, read_only=True)
    resource_usage_buckets = serializers.SerializerMethodField('get_resource_usage_buckets')

    def get_resource_usage_buckets(self, instance):
        def _dict2list(b):
            return [b['ts'], b['memory_mi'], b['cpu_m_seconds']]
        buckets = getattr(instance, 'resource_usage_buckets', [])
        return [_dict2list(b) for b in buckets]


class PodSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Pod
        fields = [
            'id',
            'uid',
            'name',
            'spec_hash',
            'started_at',
            'gone_at',
            'container_set',
        ]

    container_set = ContainerSerializer(many=True, read_only=True)


class WorkloadSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Workload
        fields = [
            'id',
            'kind',
            'namespace',
            'name',
            'affinity',
            'summary_set',
            'adjustment_set',
            'pod_set',
        ]
    serializer_choice_field = ChoiceDisplayField

    summary_set = NestedSummarySerializer(many=True, read_only=True)
    adjustment_set = AdjustmentSerializer(many=True, read_only=True)
    pod_set = PodSerializer(many=True, read_only=True)


class ResourceUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ResourceUsage
        fields = '__all__'


class SummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Summary
        fields = '__all__'


class SuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Suggestion
        fields = '__all__'
        depth = 1
