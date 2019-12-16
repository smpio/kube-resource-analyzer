from django.core.management.base import BaseCommand

from kra.collectors.pods import main


class Command(BaseCommand):
    help = 'Runs pod collector'

    def handle(self, *args, **options):
        main()
