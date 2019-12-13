import os

from django.apps import AppConfig


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kra.settings')


class App(AppConfig):
    name = 'kra'
