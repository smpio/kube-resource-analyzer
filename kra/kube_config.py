from django.conf import settings

from utils.kubernetes.config import configure


def init():
    configure(settings.KUBE_API_URL, settings.KUBE_IN_CLUSTER)
