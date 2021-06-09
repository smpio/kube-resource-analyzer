import os

from django.apps import AppConfig

from kra import kube_config

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kra.settings')
kube_config.init()


class App(AppConfig):
    name = 'kra'

    def ready(self):
        from . import signal_handlers
        signal_handlers.install()
