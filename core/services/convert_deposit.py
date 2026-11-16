from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.get_ledger_account import get_ledger_account
from core.services.market_commission import calculate_market_commission
from core.services.post_transfer import post_transfer
from ledger.models import Account
from payments.models import Deposit, DepositEvent, RateQuote
from payments.providers import get_chain_provider


@transaction.atomic
def convert_deposit(deposit: Deposit, quote: RateQuote) -> Deposit:
    locked_deposit = (
        Deposit.objects.select_for_update()
        .select_related("address__user")
        .get(pk=deposit.pk)
    )
    locked_quote = RateQuote.objects.select_for_update().get(pk=quote.pk)
    user = locked_deposit.address.user
    now = timezone.now()
    if (
        locked_deposit.state != Deposit.State.CONFIRMED
        or locked_deposit.conversion_processed_at is not None
        or locked_deposit.blacklisted
    ):
        raise ValidationError("Deposit is not confirmed and ready for conversion.")
    if (
        locked_quote.user_id != user.pk
        or locked_quote.chain != locked_deposit.address.chain
    ):
        raise ValidationError("Quote does not belong to this deposit.")
    if not locked_quote.locked_until > now or locked_quote.consumed_at is not None:
        raise ValidationError("Quote is expired or has already been used.")
    if not (
        locked_quote.amount_min_atomic
        <= locked_deposit.amount_atomic
        <= locked_quote.amount_max_atomic
    ):
        raise ValidationError("Deposit amount is outside the quote band.")
    decimals = get_chain_provider(locked_deposit.address.chain).decimals
    gross_base = (
        locked_deposit.amount_atomic
        * locked_quote.base_units_per_coin
        // (10**decimals)
    )
    if gross_base <= 0:
        raise ValidationError("Deposit converts to less than one base unit.")
    fee, credited = calculate_market_commission(gross_base)
    external = get_ledger_account(Account.Kind.EXTERNAL)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=user)
    market_fee = get_ledger_account(Account.Kind.MARKET_FEE)
    reference = f"deposit-{locked_deposit.pk}"
    post_transfer(
        external,
        available,
        credited,
        reference,
        allow_external_source=True,
    )
    post_transfer(
        external,
        market_fee,
        fee,
        reference,
        allow_external_source=True,
    )
    locked_deposit.state = Deposit.State.CREDITED
    locked_quote.consumed_at = now
    locked_quote.save(update_fields=("consumed_at",))
    locked_deposit.quote = locked_quote
    locked_deposit.base_amount = credited
    locked_deposit.conversion_processed_at = now
    locked_deposit.credited_at = now
    locked_deposit.save(
        update_fields=(
            "state",
            "support_flag",
            "quote",
            "base_amount",
            "conversion_processed_at",
            "credited_at",
            "updated_at",
        )
    )
    DepositEvent.objects.create(
        deposit=locked_deposit,
        from_state=Deposit.State.CONFIRMED,
        to_state=locked_deposit.state,
        confirmations=locked_deposit.confirmations,
        reason="credited",
    )
    return locked_deposit
