# flake8: noqa: F405

from utils.django.settings import *

env.scheme['PS_DATABASE_URL'] = (str, None)

if env('DEV_ENV'):
    env.scheme['KUBE_API_PROXY'] = (str, 'http://127.0.0.1:8001')
    env.scheme['KUBE_IN_CLUSTER'] = (bool, False)
else:
    env.scheme['KUBE_API_PROXY'] = (str, None)
    env.scheme['KUBE_IN_CLUSTER'] = (bool, True)


KUBE_API_PROXY = env('KUBE_API_PROXY')
KUBE_IN_CLUSTER = env('KUBE_IN_CLUSTER')


if env('PS_DATABASE_URL'):
    DATABASES['ps'] = env.db_url('PS_DATABASE_URL')


DATABASE_ROUTERS = ['kra.db_routers.PSRouter']
