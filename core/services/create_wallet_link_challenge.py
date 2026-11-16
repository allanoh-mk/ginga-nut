from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services._wallet_linking import _normalize_tron_address
from payments.models import WalletLink, WalletLinkChallenge


@transaction.atomic
def create_wallet_link_challenge(user, chain: str, address: str) -> WalletLinkChallenge:
    if chain != WalletLink.Chain.TRC20:
        raise ValidationError("Wallet linking is currently supported for TRON only.")

    canonical_address = _normalize_tron_address(address)
    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)
    now = timezone.now()
    WalletLinkChallenge.objects.filter(
        user=locked_user,
        consumed_at__isnull=True,
    ).update(consumed_at=now)
    return WalletLinkChallenge.objects.create(
        user=locked_user,
        chain=chain,
        address=canonical_address,
        expires_at=now + timedelta(minutes=5),
    )
