import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction

from core.services.get_ledger_account import get_ledger_account
from core.services.is_market_feature_enabled import is_market_feature_enabled
from core.services.notify import notify_user
from core.services.post_transfer import post_transfer
from core.services.reconcile_ledger import reconcile_ledger
from core.services.transition_withdrawal import transition_withdrawal
from ledger.models import Account
from payments.models import Withdrawal
from payments.providers import get_chain_provider


def process_withdrawal(withdrawal: Withdrawal) -> Withdrawal:
    send_attempted = False
    with transaction.atomic():
        locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        if locked.state == Withdrawal.State.COMPLETED:
            return locked
        if not is_market_feature_enabled("withdrawals"):
            raise ValidationError("Withdrawals are temporarily paused.")
        if locked.state == Withdrawal.State.MANUAL_APPROVAL:
            raise ValueError("Withdrawal requires manual approval.")
        if locked.state not in {
            Withdrawal.State.QUEUED,
            Withdrawal.State.APPROVED,
            Withdrawal.State.PROCESSING,
        }:
            raise ValueError(f"Withdrawal cannot be processed from {locked.state}.")
        reconcile_ledger()
        if locked.state != Withdrawal.State.PROCESSING:
            locked = transition_withdrawal(locked, "send")
        user = locked.user
        chain = locked.chain
        destination = locked.destination
        amount = locked.amount_base_units - locked.fee_base_units
        if amount <= 0:
            raise ValidationError("Withdrawal commission leaves no amount to send.")
        key = locked.idempotency_key
        provider_reference = locked.provider_reference
        pending_reference = "pending-send:" + hashlib.sha256(key.encode()).hexdigest()
        if provider_reference == pending_reference:
            raise ValidationError(
                "Withdrawal send outcome is unresolved; reconcile it before retrying."
            )
        if not provider_reference:
            locked.provider_reference = pending_reference
            locked.save(update_fields=("provider_reference", "updated_at"))
            provider_reference = pending_reference
            send_attempted = True

    if send_attempted:
        if not is_market_feature_enabled("withdrawals"):
            with transaction.atomic():
                locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
                if locked.provider_reference == pending_reference:
                    locked.provider_reference = ""
                    locked.save(update_fields=("provider_reference", "updated_at"))
            raise ValidationError("Withdrawals are temporarily paused.")
        provider_reference = get_chain_provider(chain).send_withdrawal(
            destination,
            amount,
            key,
        )
        if not provider_reference:
            raise RuntimeError("Withdrawal provider returned an empty reference.")
        with transaction.atomic():
            locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
            if locked.provider_reference == pending_reference:
                locked.provider_reference = provider_reference
                locked.save(update_fields=("provider_reference", "updated_at"))
            else:
                provider_reference = locked.provider_reference

    with transaction.atomic():
        locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        if locked.state == Withdrawal.State.COMPLETED:
            return locked
        escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=user)
        external = get_ledger_account(Account.Kind.EXTERNAL)
        post_transfer(
            escrow,
            external,
            locked.amount_base_units - locked.fee_base_units,
            f"withdrawal-send-{locked.pk}",
        )
        if locked.fee_base_units:
            market_fee = get_ledger_account(Account.Kind.MARKET_FEE)
            post_transfer(
                escrow,
                market_fee,
                locked.fee_base_units,
                f"withdrawal-fee-{locked.pk}",
            )
        completed = transition_withdrawal(locked, "complete")
        notify_user(
            completed.user,
            "withdrawal_sent",
            f"Withdrawal #{completed.pk} was sent.",
            {
                "withdrawal_id": completed.pk,
                "provider_reference": completed.provider_reference,
            },
        )
        return completed
