from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.services.get_available_balance import get_spendable_accounts
from core.services.get_ledger_account import get_ledger_account
from core.services.is_market_feature_enabled import is_market_feature_enabled
from core.services.market_commission import calculate_market_commission
from core.services.order_ledger import lock_order_accounts
from core.services.outbox import publish_on_commit
from core.services.post_transfer import post_transfer
from core.services.reconcile_ledger import reconcile_ledger
from ledger.exceptions import InsufficientFunds
from ledger.models import Account, LedgerEntry
from payments.address_validation import normalize_payout_address
from payments.models import Chain, PayoutAddress, Withdrawal
from payments.providers import get_chain_provider


@transaction.atomic
def request_withdrawal(
    user,
    chain: str,
    destination: str,
    amount_base_units: int,
    idempotency_key: str,
) -> Withdrawal:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    if isinstance(amount_base_units, bool) or not isinstance(amount_base_units, int):
        raise TypeError("Withdrawal amount must be an integer.")
    if amount_base_units <= 0:
        raise ValueError("Withdrawal amount must be positive.")
    if not isinstance(destination, str) or not destination or len(destination) > 255:
        raise ValueError("Withdrawal destination is required.")
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key
        or len(idempotency_key) > 128
    ):
        raise ValueError("A valid idempotency key is required.")
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Sign in before requesting a withdrawal.")
    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    existing = Withdrawal.objects.filter(
        user=locked_user,
        idempotency_key=idempotency_key,
    ).first()
    if existing is not None:
        if (
            existing.chain != chain
            or existing.destination != destination
            or existing.amount_base_units != amount_base_units
        ):
            raise ValidationError(
                "Idempotency key was already used for another request."
            )
        return existing
    provider = get_chain_provider(chain)
    supports_withdrawal = bool(getattr(provider, "supports_withdrawal", False))
    # Continue to honor adapters that only implemented the original plural flag.
    supports_withdrawal = supports_withdrawal or bool(
        getattr(provider, "supports_withdrawals", False)
    )
    if not supports_withdrawal:
        raise ValidationError(
            f"The configured {chain} provider does not support withdrawals."
        )
    normalized_destination = normalize_payout_address(chain, destination)
    payout_address = (
        PayoutAddress.objects.select_for_update()
        .filter(
            user=locked_user,
            chain=chain,
            address=normalized_destination,
            deleted_at__isnull=True,
        )
        .first()
    )
    if payout_address is None:
        raise ValidationError("Save this address in your payout address book first.")
    if payout_address.verified_at is None:
        raise ValidationError("Verify this payout address before withdrawing.")
    if payout_address.available_after > timezone.now():
        raise ValidationError(
            "This payout address is locked for 24 hours after being added."
        )

    if not is_market_feature_enabled("withdrawals"):
        raise ValidationError("Withdrawals are temporarily paused.")

    caps = (
        settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS,
        settings.MARKET_WITHDRAWAL_MAX_HOURLY_BASE_UNITS,
        settings.MARKET_WITHDRAWAL_MAX_DAILY_BASE_UNITS,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in caps
    ):
        raise ImproperlyConfigured(
            "Withdrawal caps must be positive integer base units."
        )
    fee, _ = calculate_market_commission(amount_base_units)
    reconcile_ledger()

    now = timezone.now()
    hour_total = (
        Withdrawal.objects.filter(
            user=locked_user,
            created_at__gte=now - timedelta(hours=1),
        ).aggregate(total=Sum("amount_base_units"))["total"]
        or 0
    )
    day_total = (
        Withdrawal.objects.filter(
            user=locked_user,
            created_at__gte=now - timedelta(days=1),
        ).aggregate(total=Sum("amount_base_units"))["total"]
        or 0
    )
    manual = (
        amount_base_units > settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS
        or hour_total + amount_base_units
        > settings.MARKET_WITHDRAWAL_MAX_HOURLY_BASE_UNITS
        or day_total + amount_base_units
        > settings.MARKET_WITHDRAWAL_MAX_DAILY_BASE_UNITS
    )
    get_ledger_account(Account.Kind.USER_AVAILABLE, owner=locked_user)
    escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=locked_user)
    available_accounts = get_spendable_accounts(locked_user)
    locked_accounts = lock_order_accounts(*available_accounts, escrow)
    current_balances = {
        account_id: (
            LedgerEntry.objects.filter(account_id=account_id).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )
        for account_id in locked_accounts
        if account_id != escrow.pk
    }
    current_balance = sum(max(balance, 0) for balance in current_balances.values())
    if current_balance < amount_base_units:
        source_id = available_accounts[0].pk
        raise InsufficientFunds(source_id, current_balance, amount_base_units)
    withdrawal = Withdrawal.objects.create(
        user=locked_user,
        chain=chain,
        destination=normalized_destination,
        amount_base_units=amount_base_units,
        fee_base_units=fee,
        idempotency_key=idempotency_key,
        state=(Withdrawal.State.MANUAL_APPROVAL if manual else Withdrawal.State.QUEUED),
    )
    remaining = amount_base_units
    for available in available_accounts:
        reserve_amount = min(
            max(current_balances[available.pk], 0),
            remaining,
        )
        if reserve_amount:
            post_transfer(
                locked_accounts[available.pk],
                locked_accounts[escrow.pk],
                reserve_amount,
                f"withdrawal-reserve-{withdrawal.pk}-{available.kind}",
            )
            remaining -= reserve_amount
        if remaining == 0:
            break
    if remaining:
        raise InsufficientFunds(
            available_accounts[0].pk,
            amount_base_units - remaining,
            amount_base_units,
        )
    if not manual:
        publish_on_commit("withdrawal", {"withdrawal_id": withdrawal.pk})
    return withdrawal
