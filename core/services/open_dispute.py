from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.order_transitions import apply_order_transition
from orders.models import Dispute, DisputeEvidence, Order
from orders.uploads import strip_image_metadata


@transaction.atomic
def open_dispute(
    order_id: int,
    actor,
    reason: str,
    evidence_kind: str,
    attachment,
    description: str = "",
) -> Dispute:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("buyer", "vendor__user")
        .get(pk=order_id)
    )
    if order.buyer_id != actor.pk:
        raise PermissionDenied("Only the buyer can open an order dispute.")
    if order.state == Order.State.DELIVERED and (
        order.finalize_at is None or order.finalize_at <= timezone.now()
    ):
        raise ValidationError("The order finalization deadline has passed.")
    if not reason.strip():
        raise ValidationError("A dispute reason is required.")
    if evidence_kind not in Dispute.EvidenceKind.values:
        raise ValidationError("Choose a valid evidence type.")
    if attachment is None:
        raise ValidationError("An evidence attachment is required.")

    dispute = Dispute.objects.create(
        order=order,
        filed_by=actor,
        reason=reason.strip(),
    )
    evidence_field = DisputeEvidence._meta.get_field("attachment")
    evidence = DisputeEvidence(
        dispute=dispute,
        submitted_by=actor,
        kind=evidence_kind,
        description=description.strip(),
    )
    evidence.attachment = evidence_field.clean(
        strip_image_metadata(attachment),
        evidence,
    )
    evidence.save()

    apply_order_transition(order, "open_dispute", actor=actor)
    order.dispute_at = timezone.now()
    order.save(update_fields=("state", "dispute_at", "updated_at"))
    return dispute
