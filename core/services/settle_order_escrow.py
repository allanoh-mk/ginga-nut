from django.core.exceptions import ValidationError

from core.services.get_ledger_account import get_ledger_account
from core.services.lock_account_owners import lock_account_owners
from core.services.notify import notify_user
from core.services.order_ledger import lock_order_accounts
from core.services.post_transfer import post_transfer
from ledger.models import Account
from orders.models import Order


def settle_order_escrow(
    order: Order,
    released_amount: int,
    refunded_amount: int,
    reference: str,
) -> None:
    if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
        raise ValidationError(
            "Monero order funds must settle through the multisig approval workflow."
        )
    if order.buyer_id is None or order.vendor_id is None:
        raise ValidationError("The order is missing buyer or vendor settlement data.")
    if (
        isinstance(released_amount, bool)
        or not isinstance(released_amount, int)
        or released_amount < 0
        or isinstance(refunded_amount, bool)
        or not isinstance(refunded_amount, int)
        or refunded_amount < 0
        or released_amount + refunded_amount != order.total_amount
    ):
        raise ValidationError("Order settlement amounts must equal the order total.")
    lock_account_owners(order.buyer, order.vendor.user)
    escrow = get_ledger_account(Account.Kind.USER_ESCROW, owner=order.buyer)
    accounts_to_lock = [escrow]
    if released_amount:
        accounts_to_lock.extend(
            (
                get_ledger_account(
                    Account.Kind.VENDOR_AVAILABLE,
                    owner=order.vendor.user,
                ),
                get_ledger_account(Account.Kind.MARKET_FEE),
                get_ledger_account(Account.Kind.TREASURY),
            )
        )
    if refunded_amount:
        accounts_to_lock.append(
            get_ledger_account(Account.Kind.USER_AVAILABLE, owner=order.buyer)
        )
    locked = lock_order_accounts(*accounts_to_lock)
    accounts = {
        (account.kind, account.owner_id): locked[account.pk]
        for account in accounts_to_lock
    }

    if released_amount:
        vendor_amount = released_amount * 95 // 100
        fee_amount = released_amount * 4 // 100
        treasury_amount = released_amount - vendor_amount - fee_amount
        for kind, owner_id, amount, suffix in (
            (
                Account.Kind.VENDOR_AVAILABLE,
                order.vendor.user_id,
                vendor_amount,
                "vendor",
            ),
            (Account.Kind.MARKET_FEE, None, fee_amount, "fee"),
            (Account.Kind.TREASURY, None, treasury_amount, "treasury"),
        ):
            if amount:
                post_transfer(
                    accounts[(Account.Kind.USER_ESCROW, order.buyer_id)],
                    accounts[(kind, owner_id)],
                    amount,
                    f"{reference}-{suffix}",
                    order=order,
                )
    if refunded_amount:
        post_transfer(
            accounts[(Account.Kind.USER_ESCROW, order.buyer_id)],
            accounts[(Account.Kind.USER_AVAILABLE, order.buyer_id)],
            refunded_amount,
            f"{reference}-refund",
            order=order,
        )
    if reference.startswith("order-finalize-"):
        message = f"Order #{order.pk} was finalized and its escrow was settled."
        notify_user(
            order.buyer,
            "order_finalized",
            message,
            {"order_id": order.pk},
        )
        notify_user(
            order.vendor.user,
            "order_finalized",
            message,
            {"order_id": order.pk},
        )
