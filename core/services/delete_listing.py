from django.core.exceptions import PermissionDenied
from django.db import transaction

from catalog.models import Listing, VendorProfile


@transaction.atomic
def delete_listing(*, actor, listing_id: int) -> None:
    profile = VendorProfile.objects.filter(user=actor).first()
    if profile is None or not profile.is_approved:
        raise PermissionDenied("An approved vendor profile is required.")

    listing = Listing.objects.select_for_update().get(
        pk=listing_id,
        vendor=profile,
    )
    listing.delete()
