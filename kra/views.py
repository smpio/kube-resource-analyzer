from rest_framework import viewsets
from django.db.models import Prefetch

from kra import tasks
from kra import models
from kra import serializers


class WorkloadViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.WorkloadSerializer

    def get_queryset(self):
        qs = models.Workload.objects.all()
        if self.request.GET.get('summary') is not None:
            qs = qs.prefetch_related('summary_set__suggestion')
        if self.request.GET.get('adjustments') is not None:
            qs = qs.prefetch_related('adjustment_set__result')
        if self.request.GET.get('pods') is not None:
            container_qs = models.Container.objects\
                .prefetch_related('oomevent_set')\
                .order_by('started_at')
            container_prefetch = Prefetch('container_set', queryset=container_qs)
            pod_qs = models.Pod.objects\
                .prefetch_related(container_prefetch)\
                .order_by('started_at')
            qs = qs.prefetch_related(Prefetch('pod_set', queryset=pod_qs))

            if self.request.GET.get('usage') is not None:
                step = self.request.GET.get('step')
                try:
                    step = int(step)
                except TypeError:
                    step = 5400
                step = max(5400, step)
                qs = qs.prefetch_resource_usage_buckets(step)

        return qs

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)

        s = getattr(serializer, 'child', serializer)

        if self.request.GET.get('summary') is None:
            del s.fields['summary_set']

        if self.request.GET.get('adjustments') is None:
            del s.fields['adjustment_set']

        if self.request.GET.get('pods') is None:
            del s.fields['pod_set']

        if self.request.GET.get('stats') is None:
            del s.fields['stats']

        step = self.request.GET.get('step')
        try:
            step = int(step)
        except TypeError:
            step = None
        s.context['stats_step'] = step

        return serializer


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

    def perform_create(self, serializer):
        adj = serializer.save()
        tasks.apply_adjustment.delay(adj.id)

    def perform_update(self, serializer):
        adj = serializer.save()
        tasks.apply_adjustment.delay(adj.id)


class SummaryViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SummarySerializer
    queryset = models.Summary.objects.all()


class SuggestionViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SuggestionSerializer
    queryset = models.Suggestion.objects.all().select_related('summary')
