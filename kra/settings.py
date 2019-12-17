# flake8: noqa: F405

from utils.django.settings import *


if env('DEV_ENV'):
    env.scheme['KUBE_API_PROXY'] = (str, 'http://127.0.0.1:8001')
    env.scheme['KUBE_IN_CLUSTER'] = (bool, False)
else:
    env.scheme['KUBE_API_PROXY'] = (str, None)
    env.scheme['KUBE_IN_CLUSTER'] = (bool, True)


KUBE_API_PROXY = env('KUBE_API_PROXY')
KUBE_IN_CLUSTER = env('KUBE_IN_CLUSTER')
