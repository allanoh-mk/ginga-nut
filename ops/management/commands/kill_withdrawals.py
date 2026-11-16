from django.core.management.base import BaseCommand

from core.services.set_market_feature import set_market_feature


class Command(BaseCommand):
    help = "Pause vendor withdrawals, or restore them with --enable."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--enable", action="store_true")

    def handle(self, *args, **options) -> None:
        enabled = options["enable"]
        set_market_feature("withdrawals", enabled)
        state = "enabled" if enabled else "PAUSED"
        self.stdout.write(self.style.SUCCESS(f"Vendor withdrawals {state}."))
