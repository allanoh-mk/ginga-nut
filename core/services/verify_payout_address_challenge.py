from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services._wallet_linking import _signature_matches_address
from payments.models import PayoutAddressChallenge

MAX_SIGNATURE_ATTEMPTS = 5


def verify_payout_address_challenge(
    user,
    challenge_id: int,
    signature: str,
) -> None:
    invalid_signature = False
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        try:
            challenge = PayoutAddressChallenge.objects.select_for_update().get(
                pk=challenge_id,
                user=user,
            )
        except PayoutAddressChallenge.DoesNotExist as error:
            raise ValidationError(
                "Address-verification challenge is unavailable."
            ) from error
        payout_address = (
            challenge.payout_address.__class__.objects.select_for_update().get(
                pk=challenge.payout_address_id,
                user=user,
            )
        )

        now = timezone.now()
        if (
            challenge.consumed_at is not None
            or challenge.expires_at <= now
            or challenge.attempts >= MAX_SIGNATURE_ATTEMPTS
            or payout_address.deleted_at is not None
        ):
            raise ValidationError("Address-verification challenge is expired or used.")
        if not _signature_matches_address(
            challenge.message_to_sign,
            signature,
            payout_address.address,
        ):
            challenge.attempts += 1
            if challenge.attempts >= MAX_SIGNATURE_ATTEMPTS:
                challenge.consumed_at = now
            challenge.save(update_fields=("attempts", "consumed_at"))
            invalid_signature = True
        else:
            payout_address.verified_at = now
            payout_address.save(update_fields=("verified_at",))
            challenge.consumed_at = now
            challenge.save(update_fields=("consumed_at",))

    if invalid_signature:
        raise ValidationError("The signature does not match the saved TRON address.")
