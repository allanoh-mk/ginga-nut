from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from catalog.models import Listing, VendorProfile


@transaction.atomic
def save_listing(*, actor, listing_id: int | None, values: dict) -> Listing:
    profile = VendorProfile.objects.filter(user=actor).first()
    if profile is None or not profile.is_approved:
        raise PermissionDenied("An approved vendor profile is required.")

    if listing_id is None:
        listing = Listing(vendor=profile)
    else:
        listing = Listing.objects.select_for_update().get(
            pk=listing_id,
            vendor=profile,
        )

    for field in (
        "category",
        "title",
        "description",
        "price",
        "stock",
        "is_active",
        "image",
        "shipping_required",
        "delivery_zone",
    ):
        if field in values:
            setattr(listing, field, values[field])
    listing.is_approved = False
    if not listing.shipping_required:
        raise ValidationError(
            "Digital listings are unavailable until digital fulfillment is supported."
        )
    if listing.pk is None:
        listing.vendor = profile
    listing.save()
    return listing
