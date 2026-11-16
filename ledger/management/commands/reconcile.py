from django.core.management.base import BaseCommand, CommandError

from core.services.reconcile_ledger import reconcile_ledger
from ledger.exceptions import LedgerImbalance


class Command(BaseCommand):
    help = "Assert that the sum of all ledger entries is zero."

    def handle(self, *args: object, **options: object) -> None:
        try:
            reconcile_ledger()
        except LedgerImbalance as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Ledger reconciled: global sum is zero."))
