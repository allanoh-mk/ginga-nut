from django.core.management.base import BaseCommand

from core.services.reserve_integrity import reserve_integrity


class Command(BaseCommand):
    help = "Measure per-chain reserve integrity and pause withdrawals on shortfall."

    def handle(self, *args: object, **options: object) -> None:
        run = reserve_integrity()
        shortfalls = ",".join(run.shortfall_chains) or "none"
        unmeasurable = (
            ",".join(item["chain"] for item in run.unmeasurable_chains) or "none"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reserve integrity run {run.pk}: "
                f"shortfall={shortfalls}, unmeasurable={unmeasurable}"
            )
        )
