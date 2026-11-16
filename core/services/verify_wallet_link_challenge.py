from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.services._wallet_linking import _signature_matches_address
from payments.models import WalletLink, WalletLinkChallenge

MAX_SIGNATURE_ATTEMPTS = 5


def verify_wallet_link_challenge(
    user,
    challenge_id: int,
    signature: str,
) -> WalletLink:
    invalid_signature = False
    wallet_link = None
    with transaction.atomic():
        try:
            challenge = WalletLinkChallenge.objects.select_for_update().get(
                pk=challenge_id,
                user=user,
            )
        except WalletLinkChallenge.DoesNotExist as error:
            raise ValidationError("Wallet-link challenge is unavailable.") from error

        now = timezone.now()
        if (
            challenge.consumed_at is not None
            or challenge.expires_at <= now
            or challenge.attempts >= MAX_SIGNATURE_ATTEMPTS
        ):
            raise ValidationError("Wallet-link challenge is expired or already used.")

        if not _signature_matches_address(
            challenge.message_to_sign,
            signature,
            challenge.address,
        ):
            challenge.attempts += 1
            if challenge.attempts >= MAX_SIGNATURE_ATTEMPTS:
                challenge.consumed_at = now
            challenge.save(update_fields=("attempts", "consumed_at"))
            invalid_signature = True
        else:
            wallet_link = (
                WalletLink.objects.select_for_update()
                .filter(
                    chain=challenge.chain,
                    address=challenge.address,
                    unlinked_at__isnull=True,
                )
                .first()
            )

            if wallet_link is None:
                try:
                    with transaction.atomic():
                        wallet_link = WalletLink.objects.create(
                            user=user,
                            chain=challenge.chain,
                            address=challenge.address,
                        )
                except IntegrityError:
                    wallet_link = (
                        WalletLink.objects.select_for_update()
                        .filter(
                            chain=challenge.chain,
                            address=challenge.address,
                            unlinked_at__isnull=True,
                        )
                        .first()
                    )

            challenge.consumed_at = now
            challenge.save(update_fields=("consumed_at",))

    if invalid_signature:
        raise ValidationError("The signature does not match that wallet address.")
    if wallet_link is None or wallet_link.user_id != user.pk:
        raise ValidationError(
            "This address is already linked to another account. Contact support."
        )
    return wallet_link
