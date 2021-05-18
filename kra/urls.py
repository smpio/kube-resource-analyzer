from utils.django.urls import urlpatterns
from utils.django.routers import Router

from . import views


router = Router()
router.register('workloads', views.WorkloadViewSet, basename='workload')
router.register('pods', views.PodViewSet, basename='pod')
router.register('containters', views.ContainerViewSet, basename='containter')
router.register('resource-usages', views.ResourceUsageViewSet, basename='resource_usage')
router.register('oom-events', views.OOMEventViewSet, basename='oom_event')
router.register('adjustments', views.AdjustmentViewSet, basename='adjustment')

router.register('workload-stats', views.WorkloadStatsView, basename='workload-stats')

urlpatterns += router.urls
