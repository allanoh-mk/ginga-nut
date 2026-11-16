import hashlib
import hmac

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.order_deadlines import FINALIZATION_LIFETIMES
from core.services.order_transitions import apply_order_transition
from orders.models import Order


@transaction.atomic
def record_delivery(order_id: int, token: str) -> Order:
    order = Order.objects.select_for_update().get(pk=order_id)
    apply_order_transition(order, "record_delivery")
    if (
        not order.pod_token_hash
        or order.pod_token_expires_at is None
        or order.pod_token_expires_at <= timezone.now()
    ):
        raise ValidationError("The proof-of-delivery token is missing or expired.")

    supplied_hash = hashlib.sha256(token.encode()).hexdigest()
    if not hmac.compare_digest(order.pod_token_hash, supplied_hash):
        raise ValidationError("Invalid proof-of-delivery token.")

    order.delivered_at = timezone.now()
    order.finalize_at = order.delivered_at + FINALIZATION_LIFETIMES[order.delivery_lane]
    order.pod_token_hash = ""
    order.pod_token_expires_at = None
    order.save(
        update_fields=(
            "state",
            "delivered_at",
            "finalize_at",
            "pod_token_hash",
            "pod_token_expires_at",
            "updated_at",
        )
    )
    return order
