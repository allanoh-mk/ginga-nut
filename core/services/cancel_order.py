from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.services.monero_order_escrow import request_monero_order_cancel
from core.services.order_transitions import apply_order_transition
from orders.models import Order


@transaction.atomic
def cancel_order(order_id: int, actor) -> Order:
    order = Order.objects.select_for_update(of=("self",)).get(pk=order_id)
    if actor is None or order.buyer_id != actor.pk:
        raise PermissionDenied("Only the order's buyer can cancel it.")
    if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
        request_monero_order_cancel(order, "buyer")
        return order
    apply_order_transition(order, "cancel", actor=actor)
    order.save(update_fields=("state", "updated_at"))
    return order
