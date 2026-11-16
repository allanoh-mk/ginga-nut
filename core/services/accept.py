from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.order_deadlines import FUNDED_VENDOR_RESPONSE_LIFETIME
from core.services.order_transitions import apply_order_transition
from orders.models import Order


@transaction.atomic
def accept(order_id: int, actor) -> Order:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("vendor__user")
        .get(pk=order_id)
    )
    if actor is None or order.vendor_id is None or order.vendor.user_id != actor.pk:
        raise PermissionDenied("Only the order's vendor can accept it.")
    apply_order_transition(order, "accept", actor=actor)
    if order.funded_at is None:
        raise ValidationError("The funded order is missing its funding timestamp.")
    if timezone.now() >= order.funded_at + FUNDED_VENDOR_RESPONSE_LIFETIME:
        raise ValidationError("The vendor response deadline has passed.")
    order.save(update_fields=("state", "updated_at"))
    return order
