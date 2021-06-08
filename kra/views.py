from rest_framework import viewsets

from kra import models
from kra import serializers
from kra.tasks.apply_adjustment import apply_adjustment


class WorkloadViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.WorkloadSerializer

    def get_queryset(self):
        qs = models.Workload.objects.all()
        if self.request.GET.get('summary') is not None:
            qs = qs.prefetch_related('summary_set__suggestion')
        if self.request.GET.get('adjustments') is not None:
            qs = qs.prefetch_related('adjustment_set__result')
        return qs

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)

        s = getattr(serializer, 'child', serializer)

        if self.request.GET.get('summary') is None:
            del s.fields['summary_set']

        if self.request.GET.get('adjustments') is None:
            del s.fields['adjustment_set']

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
        apply_adjustment.delay(adj.id)

    def perform_update(self, serializer):
        adj = serializer.save()
        apply_adjustment.delay(adj.id)


class SummaryViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SummarySerializer
    queryset = models.Summary.objects.all()


class SuggestionViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SuggestionSerializer
    queryset = models.Suggestion.objects.all().select_related('summary')
