from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from payments.models import PayoutAddress, PayoutAddressChallenge


@transaction.atomic
def delete_payout_address(user, payout_address_id: int) -> None:
    try:
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        payout_address = PayoutAddress.objects.select_for_update().get(
            pk=payout_address_id,
            user=locked_user,
            deleted_at__isnull=True,
        )
    except PayoutAddress.DoesNotExist as error:
        raise ValidationError("Payout address is unavailable.") from error

    now = timezone.now()
    payout_address.deleted_at = now
    payout_address.save(update_fields=("deleted_at",))
    PayoutAddressChallenge.objects.filter(
        user=locked_user,
        payout_address=payout_address,
        consumed_at__isnull=True,
    ).update(consumed_at=now)
