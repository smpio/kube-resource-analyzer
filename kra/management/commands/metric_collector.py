from django.core.management.base import BaseCommand

from kra.collectors.metrics import main


class Command(BaseCommand):
    help = 'Runs metric collector'

    def handle(self, *args, **options):
        main()
