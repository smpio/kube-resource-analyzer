# flake8: noqa: F405

import datetime
from utils.django.settings import *

CACHES['default'] = CACHES['locmem']

if env('DEV_ENV'):
    INSTALLED_APPS += ['corsheaders']
    MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware'] + MIDDLEWARE
    CORS_ALLOW_ALL_ORIGINS = True

env.scheme['PS_DATABASE_URL'] = (str, None)
env.scheme['MAX_RETENTION_DAYS'] = (int, 30)


if env('DEV_ENV'):
    env.scheme['KUBE_API_URL'] = (str, 'http://127.0.0.1:8001')
    env.scheme['KUBE_IN_CLUSTER'] = (bool, False)
else:
    env.scheme['KUBE_API_URL'] = (str, None)
    env.scheme['KUBE_IN_CLUSTER'] = (bool, True)


KUBE_API_URL = env('KUBE_API_URL')
KUBE_IN_CLUSTER = env('KUBE_IN_CLUSTER')

if env('PS_DATABASE_URL'):
    DATABASES['ps'] = env.db_url('PS_DATABASE_URL')
DATABASE_ROUTERS = ['kra.db_routers.PSRouter']
REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'] = None

MAX_RETENTION = datetime.timedelta(days=env('MAX_RETENTION_DAYS'))
MAX_SUMMARY_AGE = datetime.timedelta(hours=1)
BASE_MEMORY_RESERVE_FRACTION = 0.1
