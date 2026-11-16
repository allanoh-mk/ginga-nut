from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from payments.models import PayoutAddress, PayoutAddressChallenge


@transaction.atomic
def create_payout_address_challenge(
    user, payout_address_id: int
) -> PayoutAddressChallenge:
    try:
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        payout_address = PayoutAddress.objects.get(
            pk=payout_address_id,
            user=locked_user,
            deleted_at__isnull=True,
        )
    except PayoutAddress.DoesNotExist as error:
        raise ValidationError("Payout address is unavailable.") from error
    if payout_address.chain != "TRC20":
        raise ValidationError(
            "Signed ownership verification is currently supported for TRON only."
        )

    now = timezone.now()
    PayoutAddressChallenge.objects.filter(
        user=locked_user,
        consumed_at__isnull=True,
    ).update(consumed_at=now)
    return PayoutAddressChallenge.objects.create(
        user=locked_user,
        payout_address=payout_address,
        expires_at=now + timedelta(minutes=5),
    )
