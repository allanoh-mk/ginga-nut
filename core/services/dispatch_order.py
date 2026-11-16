import hashlib
import secrets
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.order_transitions import apply_order_transition
from orders.models import Order

POD_TOKEN_LIFETIME = timedelta(hours=6)


@transaction.atomic
def dispatch_order(order_id: int, actor, courier_reference: str) -> tuple[Order, str]:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("vendor__user")
        .get(pk=order_id)
    )
    if order.vendor_id is None or order.vendor.user_id != actor.pk:
        raise PermissionDenied("Only the order's vendor can dispatch it.")
    if not order.pack_photo:
        raise ValidationError("Add a pack photo before dispatching this order.")
    apply_order_transition(order, "dispatch", actor=actor)
    courier_reference = courier_reference.strip()
    if not courier_reference or len(courier_reference) > 160:
        raise ValidationError("A courier reference of 1 to 160 characters is required.")

    token = secrets.token_urlsafe(32)
    order.courier_reference = courier_reference
    order.pod_token_hash = hashlib.sha256(token.encode()).hexdigest()
    order.pod_token_expires_at = timezone.now() + POD_TOKEN_LIFETIME
    order.save(
        update_fields=(
            "courier_reference",
            "pod_token_hash",
            "pod_token_expires_at",
            "state",
            "updated_at",
        )
    )
    return order, token
