import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.services.monero_order_escrow import request_monero_order_settlement
from core.services.notify import notify_user
from core.services.order_transitions import apply_order_transition
from core.services.settle_order_escrow import settle_order_escrow
from orders.models import Dispute, Order, PublicRuling


@transaction.atomic
def rule_dispute(
    dispute_id: int,
    actor,
    amount_band: str,
    category,
    outcome: str,
    reason: str = "",
    released_amount_base_units: int | None = None,
) -> PublicRuling:
    if actor is None or not actor.is_authenticated or not actor.is_staff:
        raise PermissionDenied("Only an admin can rule on a dispute.")
    order_id = Dispute.objects.values_list("order_id", flat=True).get(pk=dispute_id)
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("listing__category", "vendor__user")
        .get(pk=order_id)
    )
    dispute = Dispute.objects.select_for_update(of=("self",)).get(pk=dispute_id)
    if order.state != Order.State.DISPUTED:
        raise ValidationError("Only an open dispute can be ruled on.")
    if PublicRuling.objects.filter(dispute=dispute).exists():
        raise ValidationError("This dispute already has a published ruling.")
    amount_band = amount_band.strip()
    match = re.fullmatch(r"(\d{1,20})-(\d{1,20}) base", amount_band)
    if match is None or int(match.group(1)) > int(match.group(2)):
        raise ValidationError("Use an amount band formatted as `min-max base`.")
    if order.listing_id is None or category.pk != order.listing.category_id:
        raise ValidationError("The ruling category must match the order listing.")
    if outcome not in PublicRuling.Outcome.values:
        raise ValidationError("Choose a valid ruling outcome.")
    reason = reason.strip()
    if not reason or len(reason) > 2000:
        raise ValidationError("A published reason of 1 to 2000 characters is required.")

    is_monero_escrow = order.payment_method == Order.PaymentMethod.XMR_MULTISIG
    if not is_monero_escrow:
        action = {
            PublicRuling.Outcome.RELEASE: "finalize",
            PublicRuling.Outcome.REFUND: "refund",
            PublicRuling.Outcome.PARTIAL: "partial",
        }[outcome]
        apply_order_transition(order, action, notify=False)
    if outcome == PublicRuling.Outcome.PARTIAL:
        if (
            isinstance(released_amount_base_units, bool)
            or not isinstance(released_amount_base_units, int)
            or not 0 < released_amount_base_units < order.total_amount
        ):
            raise ValidationError(
                "A partial ruling requires a released amount between zero and the order total."
            )
    elif released_amount_base_units is not None:
        raise ValidationError("A released amount is only valid for a partial ruling.")

    ruling = PublicRuling.objects.create(
        dispute=dispute,
        amount_band=amount_band,
        category=category,
        outcome=outcome,
        reason=reason,
    )
    message = f"Dispute ruling for order #{order.pk}: {ruling.get_outcome_display()}."
    for recipient in (order.buyer, order.vendor.user):
        notify_user(
            recipient,
            "dispute_ruling",
            message,
            {"order_id": order.pk, "dispute_id": dispute.pk},
            actor=actor,
        )
    if is_monero_escrow:
        released = (
            order.total_amount
            if outcome == PublicRuling.Outcome.RELEASE
            else (
                0
                if outcome == PublicRuling.Outcome.REFUND
                else released_amount_base_units
            )
        )
        request_monero_order_settlement(
            order,
            released_amount=released,
            refunded_amount=order.total_amount - released,
        )
        return ruling
    if outcome == PublicRuling.Outcome.RELEASE:
        settle_order_escrow(
            order,
            released_amount=order.total_amount,
            refunded_amount=0,
            reference=f"order-dispute-release-{order.pk}",
        )
        order.released_amount = order.total_amount
    elif outcome == PublicRuling.Outcome.REFUND:
        settle_order_escrow(
            order,
            released_amount=0,
            refunded_amount=order.total_amount,
            reference=f"order-dispute-refund-{order.pk}",
        )
        order.released_amount = 0
    else:
        released = released_amount_base_units
        settle_order_escrow(
            order,
            released_amount=released,
            refunded_amount=order.total_amount - released,
            reference=f"order-dispute-partial-{order.pk}",
        )
        order.released_amount = released
    order.save(update_fields=("state", "released_amount", "updated_at"))
    return ruling
