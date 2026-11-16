from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from payments.models import Withdrawal

TRANSITIONS = {
    (Withdrawal.State.MANUAL_APPROVAL, "approve"): Withdrawal.State.APPROVED,
    (Withdrawal.State.MANUAL_APPROVAL, "reject"): Withdrawal.State.REJECTED,
    (Withdrawal.State.QUEUED, "send"): Withdrawal.State.PROCESSING,
    (Withdrawal.State.APPROVED, "send"): Withdrawal.State.PROCESSING,
    (Withdrawal.State.PROCESSING, "complete"): Withdrawal.State.COMPLETED,
}


@transaction.atomic
def transition_withdrawal(
    withdrawal: Withdrawal, action: str, actor=None
) -> Withdrawal:
    locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
    target = TRANSITIONS.get((locked.state, action))
    if target is None:
        raise ValidationError(
            f"Illegal withdrawal transition: {locked.state} via {action}."
        )
    if action in {"approve", "reject"} and (actor is None or not actor.is_staff):
        raise PermissionDenied("Only an administrator can review a withdrawal.")
    if action == "complete" and not locked.provider_reference:
        raise ValidationError(
            "A provider reference is required to complete a withdrawal."
        )
    locked.state = target
    fields = ["state", "updated_at"]
    if target == Withdrawal.State.COMPLETED:
        locked.completed_at = timezone.now()
        fields.append("completed_at")
    locked.save(update_fields=fields)
    return locked
