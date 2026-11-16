from django.core.management.base import BaseCommand

from core.services.reserve_report import reserve_report


class Command(BaseCommand):
    help = "Record a reserve snapshot from ledger liabilities and configured reserves."

    def handle(self, *args: object, **options: object) -> None:
        snapshot = reserve_report()
        ratio = (
            "not measurable" if snapshot.ratio is None else f"{snapshot.ratio:.4f}:1"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reserve snapshot {snapshot.pk}: "
                f"liability={snapshot.liability_base_units}, "
                f"hot={snapshot.hot_balance_base_units}, "
                f"cold={snapshot.cold_balance_base_units}, "
                f"ratio={ratio}"
            )
        )
