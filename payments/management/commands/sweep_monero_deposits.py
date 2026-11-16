from django.core.management.base import BaseCommand

from core.services.sweep_monero_deposits import sweep_monero_deposits


class Command(BaseCommand):
    help = "Sweep Monero deposit subaddresses into the hot wallet."

    def handle(self, *args: object, **options: object) -> None:
        transaction_count = sweep_monero_deposits()
        self.stdout.write(
            self.style.SUCCESS(
                f"Monero deposit sweep completed: {transaction_count} transaction(s)."
            )
        )
