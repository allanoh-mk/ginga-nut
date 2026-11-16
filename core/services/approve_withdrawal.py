from django.db import transaction

from core.services.notify import notify_user
from core.services.outbox import publish_on_commit
from core.services.transition_withdrawal import transition_withdrawal
from payments.models import Withdrawal


@transaction.atomic
def approve_withdrawal(withdrawal: Withdrawal, admin_user) -> Withdrawal:
    locked = transition_withdrawal(withdrawal, "approve", actor=admin_user)
    publish_on_commit("withdrawal", {"withdrawal_id": locked.pk})
    notify_user(
        locked.user,
        "withdrawal_approved",
        f"Withdrawal #{locked.pk} was approved for processing.",
        {"withdrawal_id": locked.pk},
        actor=admin_user,
    )
    return locked
