from django.core.management.base import BaseCommand

from kra.collectors.oom import main


class Command(BaseCommand):
    help = 'Runs oom collector'

    def handle(self, *args, **options):
        main()
