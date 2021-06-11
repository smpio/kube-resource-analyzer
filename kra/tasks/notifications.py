import requests
from django.conf import settings

from kra.celery import task


@task
def post(message, username='KRA'):
    if not settings.DISCORD_WEBHOOK_URL:
        return
    resp = requests.post(settings.DISCORD_WEBHOOK_URL, json={
        'username': username,
        'content': message,
    })
    resp.raise_for_status()
