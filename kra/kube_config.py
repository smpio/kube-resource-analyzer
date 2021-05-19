import kubernetes
from django.conf import settings


def init():
    if settings.KUBE_API_URL:
        configuration = kubernetes.client.Configuration()
        configuration.host = settings.KUBE_API_URL
        kubernetes.client.Configuration.set_default(configuration)
    elif settings.KUBE_IN_CLUSTER:
        kubernetes.config.load_incluster_config()
    else:
        kubernetes.config.load_kube_config()
