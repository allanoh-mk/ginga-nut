from django.db.models import Sum
from django.db.models.functions import Coalesce

from ledger.models import Account

SPENDABLE_ACCOUNT_KINDS = (
    Account.Kind.USER_AVAILABLE,
    Account.Kind.VENDOR_AVAILABLE,
)


def get_spendable_accounts(user):
    return list(
        Account.objects.filter(
            owner=user,
            kind__in=SPENDABLE_ACCOUNT_KINDS,
        )
        .annotate(ledger_balance=Coalesce(Sum("entries__amount"), 0))
        .order_by("pk")
    )


def get_available_balance(user) -> int:
    return sum(
        max(account.ledger_balance, 0) for account in get_spendable_accounts(user)
    )
