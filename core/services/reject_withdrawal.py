from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.services.get_ledger_account import get_ledger_account
from core.services.post_transfer import post_transfer
from core.services.transition_withdrawal import transition_withdrawal
from ledger.models import Account
from payments.models import Withdrawal


@transaction.atomic
def reject_withdrawal(
    withdrawal: Withdrawal,
    admin_user,
    reason: str,
) -> Withdrawal:
    if admin_user is None or not admin_user.is_staff:
        raise PermissionDenied("Only an administrator can reject a withdrawal.")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValidationError("Enter a rejection reason of 1 to 500 characters.")

    locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
    if locked.state != Withdrawal.State.MANUAL_APPROVAL:
        raise ValidationError("Only withdrawals awaiting review can be rejected.")
    escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=locked.user)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=locked.user)
    post_transfer(
        escrow,
        available,
        locked.amount_base_units,
        f"withdrawal-reject-refund-{locked.pk}",
    )
    rejected = transition_withdrawal(locked, "reject", actor=admin_user)
    rejected.rejection_reason = reason.strip()
    rejected.save(update_fields=("rejection_reason", "updated_at"))
    return rejected
