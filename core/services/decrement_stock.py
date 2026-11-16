from django.db import transaction

from catalog.exceptions import InsufficientStock, ListingUnavailable
from catalog.models import Listing


@transaction.atomic
def decrement_stock(listing_id: int, quantity: int = 1) -> Listing:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError("Stock quantity must be an integer.")
    if quantity <= 0:
        raise ValueError("Stock quantity must be positive.")

    listing = (
        Listing.objects.select_for_update().select_related("vendor").get(pk=listing_id)
    )
    if (
        not listing.is_active
        or not listing.is_approved
        or not listing.vendor.is_approved
    ):
        raise ListingUnavailable("Listing is inactive or has not been approved.")
    if listing.stock < quantity:
        raise InsufficientStock(listing.stock, quantity)

    listing.stock -= quantity
    listing.save(update_fields=("stock", "updated_at"))
    return listing
