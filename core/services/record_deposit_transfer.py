from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.services.reverse_deposit import reverse_deposit
from payments.models import Chain, Deposit, DepositAddress, DepositEvent


@transaction.atomic
def record_deposit_transfer(chain: str, transfer, provider) -> Deposit:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    address = (
        DepositAddress.objects.select_for_update()
        .filter(
            chain=chain,
            address=transfer.address,
        )
        .first()
    )
    if address is None:
        raise DepositAddress.DoesNotExist(
            "Provider transfer does not match a registered deposit address."
        )
    if (
        not transfer.transaction_id
        or isinstance(transfer.confirmations, bool)
        or not isinstance(transfer.confirmations, int)
        or transfer.confirmations < 0
    ):
        raise ValueError("Provider returned invalid transfer metadata.")
    known_contract = chain != Chain.TRC20 or transfer.contract_address.lower() in {
        contract.lower() for contract in settings.TRC20_CONTRACT_WHITELIST
    }
    if known_contract:
        amount = provider.credit_amount(transfer)
    else:
        amount = transfer.amount_atomic
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("Provider returned an invalid atomic amount.")
    deposit, created = Deposit.objects.select_for_update().get_or_create(
        address=address,
        transaction_id=transfer.transaction_id,
        contract_address=transfer.contract_address,
        defaults={
            "amount_atomic": amount,
            "confirmations": transfer.confirmations,
            "last_seen_at": timezone.now(),
            "blacklisted": bool(getattr(transfer, "blacklisted", False)),
        },
    )
    if deposit.amount_atomic != amount:
        raise ValueError("Provider changed the amount for an existing transaction.")
    deposit.confirmations = transfer.confirmations
    deposit.blacklisted = bool(getattr(transfer, "blacklisted", False))
    deposit.last_seen_at = timezone.now()
    required = settings.MARKET_CHAIN_CONFIRMATIONS[chain]
    if deposit.state == Deposit.State.CREDITED and (
        deposit.confirmations < required or deposit.blacklisted or not known_contract
    ):
        deposit.save(
            update_fields=(
                "confirmations",
                "blacklisted",
                "last_seen_at",
                "updated_at",
            )
        )
        return reverse_deposit(
            deposit,
            "blacklisted" if deposit.blacklisted else "depth_drop",
        )

    deposit.save(
        update_fields=(
            "confirmations",
            "blacklisted",
            "last_seen_at",
            "updated_at",
        )
    )
    if created:
        DepositEvent.objects.create(
            deposit=deposit,
            from_state="",
            to_state=deposit.state,
            confirmations=deposit.confirmations,
            reason="first_seen",
        )
    return deposit
