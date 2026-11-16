from django.core.exceptions import ValidationError
from django.db import transaction

from core.services.decrement_stock import decrement_stock
from core.services.get_ledger_account import get_ledger_account
from ledger.models import Account
from orders.models import DeliveryZone, Order

MAX_ORDER_TOTAL = 2**63 - 1


@transaction.atomic
def create_order(
    *,
    buyer,
    listing_id: int,
    quantity: int,
    shipping_address: str = "",
    shipping_phone: str = "",
    delivery_zone: DeliveryZone | None = None,
) -> Order:
    if buyer is None or buyer.pk is None:
        raise ValidationError("An authenticated buyer is required.")
    if not isinstance(shipping_address, str) or not isinstance(shipping_phone, str):
        raise ValidationError("Shipping contact information must be text.")
    if len(shipping_address) > 255 or len(shipping_phone) > 32:
        raise ValidationError("Shipping contact information exceeds its limit.")
    if delivery_zone is not None and not isinstance(delivery_zone, DeliveryZone):
        raise ValidationError("Select a valid delivery zone.")

    listing = decrement_stock(listing_id, quantity)
    if not listing.shipping_required:
        raise ValidationError(
            "Digital listings are unavailable until digital fulfillment is supported."
        )
    if listing.delivery_zone_id is not None and (
        delivery_zone is None or delivery_zone.pk != listing.delivery_zone_id
    ):
        raise ValidationError("Select the delivery zone required by this listing.")
    if listing.shipping_required and (
        not shipping_address.strip() or not shipping_phone.strip()
    ):
        raise ValidationError("A shipping address and phone number are required.")

    total = listing.price * quantity
    if total > MAX_ORDER_TOTAL:
        raise ValidationError("The order total exceeds the supported amount.")
    delivery_type = (
        Order.DeliveryType.PHYSICAL
        if listing.shipping_required
        else Order.DeliveryType.DIGITAL
    )
    delivery_lane = (
        Order.DeliveryLane.DIGITAL
        if delivery_type == Order.DeliveryType.DIGITAL
        else (
            Order.DeliveryLane.CITY
            if delivery_zone is not None
            else Order.DeliveryLane.DOMESTIC
        )
    )

    order = Order.objects.create(
        buyer=buyer,
        vendor=listing.vendor,
        listing=listing,
        listing_title=listing.title,
        quantity=quantity,
        unit_price=listing.price,
        total_amount=total,
        delivery_type=delivery_type,
        delivery_lane=delivery_lane,
        delivery_zone=delivery_zone,
        shipping_address=shipping_address if listing.shipping_required else "",
        shipping_phone=shipping_phone if listing.shipping_required else "",
    )
    get_ledger_account(Account.Kind.USER_ESCROW, owner=buyer)
    return order
