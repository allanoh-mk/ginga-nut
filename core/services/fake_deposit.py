from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.services.convert_deposit import convert_deposit
from core.services.create_deposit_address import create_deposit_address
from core.services.promote_deposit import promote_deposit
from core.services.record_deposit_transfer import record_deposit_transfer
from payments.models import Chain, Deposit, RateQuote, RateTick
from payments.providers import get_chain_provider
from payments.providers.base import ChainTransfer, ProviderError
from payments.providers.fake import FakeProvider


@transaction.atomic
def fake_deposit(
    user,
    chain: str,
    transaction_id: str,
    amount_atomic: int,
    base_units_per_coin: int,
    confirmations: int,
) -> Deposit:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (amount_atomic, base_units_per_coin, confirmations)
    ):
        raise TypeError("Fake deposit amounts and rate must be integers.")
    if amount_atomic <= 0 or base_units_per_coin <= 0 or confirmations < 0:
        raise ValueError("Fake deposit amounts and rate must be positive.")
    configured = get_chain_provider(chain)
    if not isinstance(configured, FakeProvider):
        raise ProviderError("Fake credits are disabled when a real provider is active.")
    provider = FakeProvider(chain)
    address = create_deposit_address(user, chain)
    transfer = ChainTransfer(
        transaction_id=transaction_id,
        address=address.address,
        amount_atomic=amount_atomic,
        confirmations=confirmations,
    )
    provider.add_transfer(transfer)
    deposit = record_deposit_transfer(chain, next(iter(provider.poll())), provider)
    deposit = promote_deposit(deposit)
    if deposit.state != deposit.State.CONFIRMED:
        return deposit

    now = timezone.now()
    source_a = RateTick.objects.create(
        chain=chain,
        source="fake-a",
        base_units_per_coin=base_units_per_coin,
        observed_at=now,
    )
    source_b = RateTick.objects.create(
        chain=chain,
        source="fake-b",
        base_units_per_coin=base_units_per_coin,
        observed_at=now,
    )
    quote = RateQuote.objects.create(
        user=user,
        chain=chain,
        source_a=source_a,
        source_b=source_b,
        base_units_per_coin=base_units_per_coin,
        amount_min_atomic=amount_atomic,
        amount_max_atomic=amount_atomic,
        locked_until=now + timedelta(minutes=10),
    )
    return convert_deposit(deposit, quote)
