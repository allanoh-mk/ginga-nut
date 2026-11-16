from django.db import transaction
from django.db.models import Sum

from core.services.get_ledger_account import get_ledger_account
from core.services.post_transfer import post_transfer
from ledger.models import Account, LedgerEntry
from payments.models import Deposit, DepositEvent


@transaction.atomic
def reverse_deposit(deposit: Deposit, reason: str) -> Deposit:
    locked = (
        Deposit.objects.select_for_update()
        .select_related("address__user")
        .get(pk=deposit.pk)
    )
    if locked.state == Deposit.State.REVERSED:
        return locked
    previous_state = locked.state
    if locked.state != Deposit.State.CREDITED or locked.base_amount <= 0:
        locked.state = Deposit.State.ORPHANED
        locked.support_flag = True
        locked.save(update_fields=("state", "support_flag", "updated_at"))
        DepositEvent.objects.create(
            deposit=locked,
            from_state=previous_state,
            to_state=locked.state,
            confirmations=locked.confirmations,
            reason="orphaned",
        )
        return locked

    user_available = get_ledger_account(
        Account.Kind.USER_AVAILABLE,
        owner=locked.address.user,
    )
    external = get_ledger_account(Account.Kind.EXTERNAL)
    suspense = get_ledger_account(Account.Kind.SUSPENSE)
    market_fee = get_ledger_account(Account.Kind.MARKET_FEE)
    treasury = get_ledger_account(Account.Kind.TREASURY)
    balance = (
        LedgerEntry.objects.filter(account=user_available).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    recoverable = min(max(balance, 0), locked.base_amount)
    reference = f"deposit-reversal-{locked.pk}"
    if recoverable:
        post_transfer(user_available, external, recoverable, reference)
    shortfall = locked.base_amount - recoverable
    if shortfall:
        post_transfer(
            suspense,
            external,
            shortfall,
            reference,
            allow_suspense_debt=True,
        )

    fee_reference = f"deposit-{locked.pk}"
    commission = (
        LedgerEntry.objects.filter(
            ref=fee_reference,
            account=market_fee,
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    remaining_commission = max(commission, 0)
    for source in (market_fee, treasury):
        if remaining_commission == 0:
            break
        balance = (
            LedgerEntry.objects.filter(account=source).aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        refund = min(max(balance, 0), remaining_commission)
        if refund:
            post_transfer(
                source,
                external,
                refund,
                f"{reference}-fee-{source.kind}",
            )
            remaining_commission -= refund
    if remaining_commission:
        post_transfer(
            suspense,
            external,
            remaining_commission,
            f"{reference}-fee-shortfall",
            allow_suspense_debt=True,
        )

    locked.state = Deposit.State.REVERSED
    locked.support_flag = True
    locked.save(update_fields=("state", "support_flag", "updated_at"))
    DepositEvent.objects.create(
        deposit=locked,
        from_state=previous_state,
        to_state=locked.state,
        confirmations=locked.confirmations,
        reason=reason[:48],
    )
    return locked
