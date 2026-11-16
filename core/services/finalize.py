from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.monero_order_escrow import request_monero_order_settlement
from core.services.order_transitions import apply_order_transition
from core.services.settle_order_escrow import settle_order_escrow
from orders.models import Order


@transaction.atomic
def finalize(order_id: int, now=None) -> Order:
    order = Order.objects.select_for_update(of=("self",)).get(pk=order_id)
    if order.state != Order.State.DELIVERED:
        raise ValidationError("Only delivered orders can be finalized by the timer.")
    now = now or timezone.now()
    if order.finalize_at is None or now < order.finalize_at:
        raise ValidationError("The order finalization deadline has not passed.")

    amount = order.total_amount
    if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
        request_monero_order_settlement(
            order,
            released_amount=amount,
            refunded_amount=0,
        )
        return order
    settle_order_escrow(
        order,
        released_amount=amount,
        refunded_amount=0,
        reference=f"order-finalize-{order.pk}",
    )
    apply_order_transition(order, "finalize", notify=False)
    order.released_amount = amount
    order.save(update_fields=("state", "released_amount", "updated_at"))
    return order
