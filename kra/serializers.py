import datetime
from collections import defaultdict

from django.conf import settings
from django.db.models import Q
from rest_framework import serializers

from utils.django.serializers.fields import ChoiceDisplayField

from . import models
from .qs import to_buckets


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


class WorkloadSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Workload
        fields = [
            'id',
            'kind',
            'namespace',
            'name',
            'priority',
            'auto_downgrade',
            'min_auto_downgrade_interval_sec',
            'summary_set',
            'stats',
        ]
    serializer_choice_field = ChoiceDisplayField

    summary_set = NestedSummarySerializer(many=True, read_only=True)
    stats = serializers.SerializerMethodField('get_stats')

    def get_stats(self, workload):
        step = self.context.get('stats_step')

        since = datetime.datetime.now() - settings.MAX_RETENTION
        stats = defaultdict(dict)

        containers = models.Container.objects\
            .filter(pod__workload=workload)\
            .filter(Q(pod__gone_at__gt=since) | Q(pod__gone_at=None))\
            .order_by('pod__started_at')\
            .select_related('pod')

        container_ids_by_name = defaultdict(list)
        for container in containers:
            container_ids_by_name[container.name].append(container.id)

            if 'requests' not in stats[container.name]:
                stats[container.name]['requests'] = []
            stats[container.name]['requests'].append({
                'since': container.pod.started_at,
                'till': container.pod.gone_at,
                'memory_limit_mi': container.memory_limit_mi,
                'cpu_request_m': container.cpu_request_m,
            })

        for container_name, container_ids in container_ids_by_name.items():
            if step:
                usage_measurements = to_buckets(
                    models.ResourceUsage.objects\
                        .filter(container__in=container_ids, measured_at__gt=since),
                    step,
                    'measured_at',
                    'memory_mi',
                    'cpu_m_seconds',
                )

                stats[container_name]['usage'] = list(usage_measurements)
            else:
                usage_measurements = models.ResourceUsage.objects \
                    .filter(container__in=container_ids, measured_at__gt=since) \
                    .order_by('measured_at')
                stats[container_name]['usage'] = ResourceUsageSerializer(usage_measurements, many=True).data

            oom_events = models.OOMEvent.objects\
                .filter(container__in=container_ids, happened_at__gt=since) \
                .order_by('happened_at')
            stats[container_name]['oom_events'] = OOMEventSerializer(oom_events, many=True).data

        return stats


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


class SummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Summary
        fields = '__all__'


class SuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Suggestion
        fields = '__all__'
        depth = 1
