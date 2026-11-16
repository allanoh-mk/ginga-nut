from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from payments.models import Chain, DepositAddress
from payments.providers import get_chain_provider


@transaction.atomic
def create_deposit_address(user, chain: str) -> DepositAddress:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    provider = get_chain_provider(chain)
    if not provider.supports_deposit:
        raise ValidationError(
            f"The configured {chain} provider does not support deposits."
        )
    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    existing = DepositAddress.objects.filter(user=locked_user, chain=chain).first()
    if existing is not None:
        return existing
    address, provider_reference = provider.new_address(locked_user, chain)
    if not address:
        raise ValueError("Provider returned an empty deposit address.")
    return DepositAddress.objects.create(
        user=locked_user,
        chain=chain,
        address=address,
        provider_reference=provider_reference,
    )
