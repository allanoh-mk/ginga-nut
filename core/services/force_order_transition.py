from django.core.exceptions import ValidationError
from django.db import transaction

from core.services.accept import accept
from core.services.order_transitions import ORDER_TRANSITIONS
from orders.models import Order, StaffOrderTransition


@transaction.atomic
def force_order_transition(
    order_id: int,
    target_state: str,
    actor,
    reason: str,
) -> StaffOrderTransition:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError("A reason is required for a staff transition.")

    order = Order.objects.select_for_update().get(pk=order_id)
    previous_state = order.state
    valid_targets = {
        target
        for (source, _action), target in ORDER_TRANSITIONS.items()
        if source == previous_state
    }
    if target_state not in valid_targets:
        raise ValidationError(
            f"{target_state} is not a valid next state from {previous_state}."
        )
    if target_state == Order.State.ACCEPTED and order.state == Order.State.FUNDED:
        if order.vendor_id is None:
            raise ValidationError("The order has no vendor to accept it.")
        changed_order = accept(order.pk, order.vendor.user)
    else:
        raise ValidationError(
            f"Staff cannot force {previous_state} to {target_state}. "
            "Use its domain workflow so financial and fulfillment side effects run."
        )
    if changed_order.state != target_state:
        raise ValidationError("The domain workflow did not reach the requested state.")
    return StaffOrderTransition.objects.create(
        order=order,
        actor=actor,
        from_state=previous_state,
        to_state=target_state,
        reason=normalized_reason,
    )
