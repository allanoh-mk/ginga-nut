from django.db import transaction
from django.db.models import Sum

from ledger.exceptions import InsufficientFunds
from ledger.models import Account, LedgerEntry


@transaction.atomic
def post_transfer(
    from_account: Account,
    to_account: Account,
    amount: int,
    ref: str,
    *,
    allow_external_source: bool = False,
    allow_suspense_debt: bool = False,
    order=None,
) -> tuple[LedgerEntry, LedgerEntry]:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("Transfer amount must be an integer.")
    if amount <= 0:
        raise ValueError("Transfer amount must be positive.")
    if not isinstance(ref, str) or not ref or len(ref) > 255:
        raise ValueError("Transfer reference must contain 1 to 255 characters.")
    if not isinstance(from_account, Account) or not isinstance(to_account, Account):
        raise TypeError("Transfer endpoints must be Account instances.")
    if from_account.pk is None or to_account.pk is None:
        raise ValueError("Transfer accounts must be saved.")
    if from_account.pk == to_account.pk:
        raise ValueError("Transfer accounts must be different.")

    account_ids = sorted((from_account.pk, to_account.pk))
    locked_accounts = {
        account.pk: account
        for account in Account.objects.select_for_update()
        .filter(pk__in=account_ids)
        .order_by("pk")
    }
    if len(locked_accounts) != 2:
        raise Account.DoesNotExist("A transfer account no longer exists.")

    locked_from = locked_accounts[from_account.pk]
    locked_to = locked_accounts[to_account.pk]
    available = (
        LedgerEntry.objects.filter(account=locked_from).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    if locked_from.kind == Account.Kind.EXTERNAL and not allow_external_source:
        raise ValueError("External credits must use the deposit-credit service.")
    if allow_suspense_debt and locked_from.kind != Account.Kind.SUSPENSE:
        raise ValueError("Only suspense may record a reversal debt.")
    if (
        locked_from.kind != Account.Kind.EXTERNAL
        and not allow_suspense_debt
        and available < amount
    ):
        raise InsufficientFunds(locked_from.pk, available, amount)

    debit = LedgerEntry.objects.create(
        account=locked_from,
        order=order,
        amount=-amount,
        ref=ref,
    )
    credit = LedgerEntry.objects.create(
        account=locked_to,
        order=order,
        amount=amount,
        ref=ref,
    )
    return debit, credit
