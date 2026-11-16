from django.core.management.base import BaseCommand

from core.services.poll_deposits import poll_deposits
from payments.models import Chain


class Command(BaseCommand):
    help = "Poll a chain provider and record inbound transfers."

    def add_arguments(self, parser) -> None:
        parser.add_argument("chain", choices=Chain.values)

    def handle(self, *args, **options) -> None:
        deposits = poll_deposits(options["chain"])
        self.stdout.write(f"Recorded or updated {len(deposits)} deposits.")
