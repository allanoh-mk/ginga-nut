from django.core.exceptions import ValidationError

from core.services.notify import notify_user
from orders.models import Order

ORDER_TRANSITIONS = {
    (Order.State.DRAFT, "fund"): Order.State.FUNDED,
    (Order.State.DRAFT, "expire"): Order.State.EXPIRED,
    (Order.State.DRAFT, "cancel"): Order.State.CANCELLED,
    (Order.State.DRAFT, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
    (Order.State.FUNDED, "accept"): Order.State.ACCEPTED,
    (Order.State.FUNDED, "reject"): Order.State.REFUNDED,
    (Order.State.FUNDED, "expire_funding"): Order.State.REFUNDED,
    (Order.State.FUNDED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
    (Order.State.ACCEPTED, "pack"): Order.State.PACKED,
    (Order.State.ACCEPTED, "digital_delivery"): Order.State.DELIVERED,
    (Order.State.PACKED, "dispatch"): Order.State.DISPATCHED,
    (Order.State.DISPATCHED, "record_delivery"): Order.State.DELIVERED,
    (Order.State.DISPATCHED, "open_dispute"): Order.State.DISPUTED,
    (Order.State.DELIVERED, "open_dispute"): Order.State.DISPUTED,
    (Order.State.DELIVERED, "finalize"): Order.State.FINALIZED,
    (Order.State.DELIVERED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
    (Order.State.DISPUTED, "finalize"): Order.State.FINALIZED,
    (Order.State.DISPUTED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
    (Order.State.DISPUTED, "refund"): Order.State.REFUNDED,
    (Order.State.DISPUTED, "partial"): Order.State.PARTIAL,
    (Order.State.SETTLEMENT_PENDING, "xmr_release"): Order.State.FINALIZED,
    (Order.State.SETTLEMENT_PENDING, "xmr_refund"): Order.State.REFUNDED,
    (Order.State.SETTLEMENT_PENDING, "xmr_partial"): Order.State.PARTIAL,
    (Order.State.CANCELLED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
    (Order.State.EXPIRED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
}


def transition_target(state: str, action: str) -> str:
    target = ORDER_TRANSITIONS.get((state, action))
    if target is None:
        raise ValidationError(f"Illegal order transition: {state} via {action}.")
    return target


def apply_order_transition(
    order: Order,
    action: str,
    *,
    actor=None,
    notify: bool = True,
) -> None:
    order.state = transition_target(order.state, action)
    if not notify:
        return

    data = {"order_id": order.pk}
    buyer = order.buyer
    vendor_user = order.vendor.user if order.vendor_id else None
    if action == "fund":
        recipients = ((vendor_user, Order.State.FUNDED, "Order funded"),)
        notification_type = "order_funded"
    elif action == "cancel":
        recipients = ((vendor_user, order.state, "Order cancelled by the buyer"),)
        notification_type = "order_cancelled"
    elif action == "expire":
        recipients = ((buyer, order.state, "Order expired before funding"),)
        notification_type = "order_expired"
    elif action == "accept":
        recipients = ((buyer, Order.State.ACCEPTED, "Order accepted"),)
        notification_type = "order_accepted"
    elif action == "reject":
        message = "The vendor rejected the order and its escrow was refunded"
        recipients = ((buyer, order.state, message),)
        notification_type = "order_rejected"
    elif action == "expire_funding":
        message = "The vendor response deadline expired and the escrow was refunded"
        recipients = ((buyer, order.state, message),)
        notification_type = "order_expired"
    elif action == "xmr_refund":
        message = "The order escrow was refunded"
        recipients = ((buyer, order.state, message),)
        notification_type = "order_refunded"
    elif action == "pack":
        recipients = ((buyer, Order.State.PACKED, "Order packed"),)
        notification_type = "order_packed"
    elif action == "dispatch":
        recipients = ((buyer, Order.State.DISPATCHED, "Order dispatched"),)
        notification_type = "order_dispatched"
    elif action in {"record_delivery", "digital_delivery"}:
        recipients = ((buyer, Order.State.DELIVERED, "Order delivered"),)
        notification_type = "order_delivered"
    elif action in {"finalize", "xmr_release"}:
        recipients = (
            (buyer, Order.State.FINALIZED, "Order finalized"),
            (vendor_user, Order.State.FINALIZED, "Order finalized"),
        )
        notification_type = "order_finalized"
    elif action == "open_dispute":
        recipients = (
            (buyer, Order.State.DISPUTED, "A dispute was opened for the order"),
            (vendor_user, Order.State.DISPUTED, "A dispute was opened for the order"),
        )
        notification_type = "dispute_opened"
    elif action == "xmr_settlement_pending":
        recipients = (
            (buyer, order.state, "Order settlement is pending"),
            (vendor_user, order.state, "Order settlement is pending"),
        )
        notification_type = "settlement_pending"
    elif action == "xmr_partial":
        recipients = (
            (buyer, order.state, "Monero order settlement completed"),
            (vendor_user, order.state, "Monero order settlement completed"),
        )
        notification_type = "settlement_completed"
    else:
        return

    for recipient, _, message in recipients:
        if recipient is not None:
            notify_user(
                recipient,
                notification_type,
                f"{message} #{order.pk}.",
                data,
                actor=actor,
            )
