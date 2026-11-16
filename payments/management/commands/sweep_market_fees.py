from django.core.management.base import BaseCommand

from core.services.sweep_market_fees import sweep_market_fees


class Command(BaseCommand):
    help = "Move accumulated market fees and spreads into the treasury."

    def handle(self, *args: object, **options: object) -> None:
        swept = sweep_market_fees()
        self.stdout.write(
            self.style.SUCCESS(f"Swept {swept} base units into the treasury.")
        )
