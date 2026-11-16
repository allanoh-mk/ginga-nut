from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from orders.models import Order

MAX_FINALIZE_EXTENSIONS = 2
FINALIZE_EXTENSION = timedelta(hours=24)


@transaction.atomic
def extend_finalize(order_id: int, actor) -> Order:
    order = Order.objects.select_for_update(of=("self",)).get(pk=order_id)
    if order.buyer_id != actor.pk:
        raise PermissionDenied("Only the order's buyer can extend finalization.")
    if order.state != Order.State.DELIVERED:
        raise ValidationError("Only delivered orders can extend finalization.")
    now = timezone.now()
    if order.finalize_at is None or order.finalize_at <= now:
        raise ValidationError("The finalization deadline has passed.")
    if order.buyer_extensions >= MAX_FINALIZE_EXTENSIONS:
        raise ValidationError(
            "The finalization deadline has already been extended twice."
        )

    order.finalize_at += FINALIZE_EXTENSION
    order.buyer_extensions += 1
    order.save(update_fields=("finalize_at", "buyer_extensions", "updated_at"))
    return order
