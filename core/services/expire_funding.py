from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.services.get_ledger_account import get_ledger_account
from core.services.monero_order_escrow import (
    request_monero_order_cancel,
    request_monero_order_settlement,
)
from core.services.order_deadlines import (
    DRAFT_FUNDING_LIFETIME,
    FUNDED_VENDOR_RESPONSE_LIFETIME,
)
from core.services.order_ledger import lock_order_accounts
from core.services.order_transitions import apply_order_transition
from core.services.post_transfer import post_transfer
from ledger.models import Account
from orders.models import Order


@transaction.atomic
def expire_funding(order_id: int, now=None) -> Order:
    order = Order.objects.select_for_update(of=("self",)).get(pk=order_id)
    now = now or timezone.now()
    if order.state == Order.State.DRAFT:
        if order.expires_at is None and order.created_at is None:
            raise ValidationError("The draft funding deadline is unavailable.")
        deadline = order.expires_at or (order.created_at + DRAFT_FUNDING_LIFETIME)
        if now < deadline:
            raise ValidationError("The order funding deadline has not passed.")
        if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
            request_monero_order_cancel(order, "deadline")
            return order
        apply_order_transition(order, "expire")
        order.save(update_fields=("state", "updated_at"))
        return order

    if order.state == Order.State.FUNDED:
        if (
            order.funded_at is None
            or order.buyer_id is None
            or order.total_amount is None
        ):
            raise ValidationError("The funded order is missing settlement data.")
        deadline = order.funded_at + FUNDED_VENDOR_RESPONSE_LIFETIME
        if now < deadline:
            raise ValidationError("The vendor response deadline has not passed.")
        if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
            request_monero_order_settlement(
                order,
                released_amount=0,
                refunded_amount=order.total_amount,
            )
            return order
        apply_order_transition(order, "expire_funding")
        escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=order.buyer)
        available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=order.buyer)
        accounts = lock_order_accounts(escrow, available)
        post_transfer(
            accounts[escrow.pk],
            accounts[available.pk],
            order.total_amount,
            f"order-timeout-refund-{order.pk}",
            order=order,
        )
        order.save(update_fields=("state", "updated_at"))
        return order

    apply_order_transition(order, "expire_funding")
