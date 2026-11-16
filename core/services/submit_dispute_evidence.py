from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from orders.models import Dispute, DisputeEvidence
from orders.uploads import strip_image_metadata


@transaction.atomic
def submit_dispute_evidence(
    dispute_id: int,
    actor,
    kind: str,
    attachment,
    description: str = "",
) -> DisputeEvidence:
    dispute = (
        Dispute.objects.select_for_update(of=("self",))
        .select_related("order__buyer", "order__vendor__user")
        .get(pk=dispute_id)
    )
    vendor_user_id = (
        dispute.order.vendor.user_id if dispute.order.vendor_id is not None else None
    )
    participants = {dispute.order.buyer_id, vendor_user_id}
    if actor.pk not in participants:
        raise PermissionDenied("Only an order participant can submit evidence.")
    if dispute.order.state != dispute.order.State.DISPUTED:
        raise ValidationError("Evidence can only be submitted to an open dispute.")
    if kind not in Dispute.EvidenceKind.values:
        raise ValidationError("Choose a valid evidence type.")
    if attachment is None:
        raise ValidationError("An evidence attachment is required.")

    evidence = DisputeEvidence(
        dispute=dispute,
        submitted_by=actor,
        kind=kind,
        description=description.strip(),
    )
    evidence.attachment = DisputeEvidence._meta.get_field("attachment").clean(
        strip_image_metadata(attachment),
        evidence,
    )
    evidence.save()
    return evidence
