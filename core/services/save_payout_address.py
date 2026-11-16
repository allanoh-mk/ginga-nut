from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from payments.address_validation import normalize_payout_address
from payments.models import Chain, PayoutAddress

PAYOUT_ADDRESS_LOCK = timedelta(hours=24)


@transaction.atomic
def save_payout_address(
    user,
    chain: str,
    address: str,
    address_confirmation: str,
    label: str,
) -> PayoutAddress:
    if chain not in Chain.values:
        raise ValidationError("Choose a supported chain.")
    if not isinstance(address, str) or not isinstance(address_confirmation, str):
        raise ValidationError("Enter the payout address twice.")
    normalized_address = normalize_payout_address(chain, address)
    confirmed_address = normalize_payout_address(chain, address_confirmation)
    if normalized_address != confirmed_address:
        raise ValidationError("The payout addresses do not match.")
    normalized_label = label.strip() if isinstance(label, str) else ""
    if not normalized_label or len(normalized_label) > 64:
        raise ValidationError("Enter a label of 1 to 64 characters.")

    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    existing = PayoutAddress.objects.filter(
        user=locked_user,
        chain=chain,
        address=normalized_address,
        deleted_at__isnull=True,
    ).first()
    if existing is not None:
        raise ValidationError("This payout address is already saved.")
    try:
        with transaction.atomic():
            return PayoutAddress.objects.create(
                user=locked_user,
                chain=chain,
                address=normalized_address,
                label=normalized_label,
                available_after=timezone.now() + PAYOUT_ADDRESS_LOCK,
            )
    except IntegrityError as error:
        raise ValidationError("This payout address is already saved.") from error
