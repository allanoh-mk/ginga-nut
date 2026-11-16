from django.core.management import call_command
from django.core.management.base import BaseCommand

from core.services.is_market_feature_enabled import is_market_feature_enabled


class Command(BaseCommand):
    help = "Process queued and approved vendor withdrawals."

    def handle(self, *args, **options) -> None:
        if not is_market_feature_enabled("withdrawals"):
            self.stdout.write(
                "Withdrawals are paused; queued jobs were left untouched."
            )
            return
        call_command("run_market_worker", "--once")
        self.stdout.write("Processed available financial jobs.")
