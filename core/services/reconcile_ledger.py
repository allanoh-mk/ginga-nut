from django.db.models import Sum

from ledger.exceptions import LedgerImbalance
from ledger.models import LedgerEntry


def reconcile_ledger() -> int:
    total = LedgerEntry.objects.aggregate(total=Sum("amount"))["total"] or 0
    if total != 0:
        raise LedgerImbalance(total)
    return total
