from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.services.get_ledger_account import get_ledger_account
from core.services.post_transfer import post_transfer
from ledger.models import Account, LedgerEntry


@transaction.atomic
def sweep_market_fees() -> int:
    fee = get_ledger_account(Account.Kind.MARKET_FEE)
    spread = get_ledger_account(Account.Kind.MARKET_SPREAD)
    treasury = get_ledger_account(Account.Kind.TREASURY)
    account_ids = sorted((fee.pk, spread.pk, treasury.pk))
    locked = {
        account.pk: account
        for account in Account.objects.select_for_update()
        .filter(pk__in=account_ids)
        .order_by("pk")
    }
    if len(locked) != len(account_ids):
        raise Account.DoesNotExist("A market-fee account no longer exists.")

    reference = f"daily-market-fee-sweep-{timezone.localdate().isoformat()}"
    swept = 0
    for source_id in (fee.pk, spread.pk):
        source = locked[source_id]
        balance = (
            LedgerEntry.objects.filter(account=source).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        if balance <= 0:
            continue
        post_transfer(
            source,
            locked[treasury.pk],
            balance,
            f"{reference}-{source.kind}",
        )
        swept += balance
    return swept
