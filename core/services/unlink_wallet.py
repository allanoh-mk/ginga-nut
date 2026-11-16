from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from payments.models import WalletLink, WalletLinkChallenge


@transaction.atomic
def unlink_wallet(user, wallet_id: int) -> None:
    try:
        user.__class__.objects.select_for_update().get(pk=user.pk)
        wallet = WalletLink.objects.get(
            pk=wallet_id,
            user=user,
            unlinked_at__isnull=True,
        )
    except WalletLink.DoesNotExist as error:
        raise ValidationError("Linked wallet is unavailable.") from error

    pending_challenges = WalletLinkChallenge.objects.filter(
        user=user,
        chain=wallet.chain,
        address=wallet.address,
        consumed_at__isnull=True,
    ).order_by("pk")
    list(pending_challenges.select_for_update())
    wallet = WalletLink.objects.select_for_update().get(pk=wallet.pk)

    now = timezone.now()
    wallet.unlinked_at = now
    wallet.save(update_fields=("unlinked_at",))
    pending_challenges.update(consumed_at=now)
