from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.get_ledger_account import get_ledger_account
from core.services.order_deadlines import DRAFT_FUNDING_LIFETIME
from core.services.order_ledger import lock_order_accounts
from core.services.order_transitions import apply_order_transition
from core.services.post_transfer import post_transfer
from ledger.models import Account, LedgerEntry
from orders.models import Order


@transaction.atomic
def fund_order(order_id: int, actor) -> Order:
    order = Order.objects.select_for_update(of=("self",)).get(pk=order_id)
    if actor is None or order.buyer_id != actor.pk:
        raise PermissionDenied("Only the order's buyer can fund it.")
    if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
        if order.funded_at is not None and order.state != Order.State.DRAFT:
            return order
        raise ValidationError(
            "This order is using Monero multisig. Wait for its funding confirmation."
        )

    ref = f"order-fund-{order.pk}"
    if order.state != Order.State.DRAFT:
        fund_entries = list(
            LedgerEntry.objects.filter(ref=ref, order=order).values_list(
                "amount",
                "account__kind",
                "account__owner_id",
            )
        )
        expected_entries = []
        if order.total_amount is not None:
            expected_entries = sorted(
                (
                    (-order.total_amount, Account.Kind.USER_AVAILABLE, order.buyer_id),
                    (order.total_amount, Account.Kind.USER_ESCROW, order.buyer_id),
                )
            )
        if order.funded_at is not None and sorted(fund_entries) == expected_entries:
            return order
        apply_order_transition(order, "fund", actor=actor)

    now = timezone.now()
    deadline = order.expires_at or (
        order.created_at + DRAFT_FUNDING_LIFETIME
        if order.created_at is not None
        else None
    )
    if deadline is None:
        raise ValidationError("The order funding deadline is unavailable.")
    if now >= deadline:
        raise ValidationError("The order funding deadline has passed.")
    if order.buyer_id is None or order.total_amount is None:
        raise ValidationError("The order is missing buyer or amount data.")
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=order.buyer)
    escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=order.buyer)
    accounts = lock_order_accounts(available, escrow)
    post_transfer(
        accounts[available.pk],
        accounts[escrow.pk],
        order.total_amount,
        ref,
        order=order,
    )
    order.funded_at = now
    apply_order_transition(order, "fund", actor=actor)
    order.save(update_fields=("state", "funded_at", "updated_at"))
    return order
