from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.services.get_ledger_account import get_ledger_account
from core.services.monero_order_escrow import request_monero_order_settlement
from core.services.order_ledger import lock_order_accounts
from core.services.order_transitions import apply_order_transition
from core.services.post_transfer import post_transfer
from ledger.models import Account
from orders.models import Order


@transaction.atomic
def reject(order_id: int, actor) -> Order:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("vendor__user")
        .get(pk=order_id)
    )
    if actor is None or order.vendor_id is None or order.vendor.user_id != actor.pk:
        raise PermissionDenied("Only the order's vendor can reject it.")
    if order.buyer_id is None or order.total_amount is None:
        raise ValidationError("The order is missing buyer or amount data.")
    if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
        request_monero_order_settlement(
            order,
            released_amount=0,
            refunded_amount=order.total_amount,
        )
        return order
    apply_order_transition(order, "reject", actor=actor)
    escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=order.buyer)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=order.buyer)
    accounts = lock_order_accounts(escrow, available)
    post_transfer(
        accounts[escrow.pk],
        accounts[available.pk],
        order.total_amount,
        f"order-reject-refund-{order.pk}",
        order=order,
    )
    order.save(update_fields=("state", "updated_at"))
    return order
