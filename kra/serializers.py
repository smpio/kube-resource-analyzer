import datetime
from collections import defaultdict

from django.db.models import Q, Func, Value, DateTimeField, Max
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


class TimeBucket(Func):
    function = 'time_bucket'


def to_buckets(qs, bucket_size_sec, time_field, *fields):
    bucket_size = f'{bucket_size_sec} seconds'
    p = '_bucket_'

    qs = qs\
        .annotate(**{
            p+time_field: TimeBucket(Value(bucket_size), time_field, output_field=DateTimeField())
        })\
        .values(p+time_field)\
        .order_by(p+time_field)

    for field in fields:
        qs = qs.annotate(**{
            p+field: Max(field),
        })

    for result in qs:
        result[time_field] = result[p+time_field]
        del result[p+time_field]
        for field in fields:
            result[field] = result[p+field]
            del result[p+field]

    return qs


class WorkloadStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Workload
        fields = '__all__'
    serializer_choice_field = ChoiceDisplayField

    stats = serializers.SerializerMethodField('get_stats')

    def get_stats(self, workload):
        since = datetime.datetime.now() - datetime.timedelta(days=30)
        stats = defaultdict(dict)

        request = self.context.get('request')
        if request:
            step = request.GET.get('step')
            try:
                step = int(step)
            except TypeError:
                step = None
        else:
            step = None

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
