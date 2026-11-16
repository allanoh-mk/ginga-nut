from django.core.management.base import BaseCommand

from core.services.set_market_feature import set_market_feature


class Command(BaseCommand):
    help = "Pause new orders, or restore order creation with --enable."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--enable", action="store_true")

    def handle(self, *args, **options) -> None:
        enabled = options["enable"]
        set_market_feature("new_orders", enabled)
        state = "enabled" if enabled else "PAUSED"
        self.stdout.write(self.style.SUCCESS(f"New orders {state}."))
