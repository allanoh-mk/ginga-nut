import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import transaction
from django.utils import timezone

from core.services.issue_rate_quote import issue_xmr_rate_quote_for_base_amount
from core.services.market_commission import calculate_market_commission
from core.services.order_transitions import apply_order_transition
from core.services.outbox import publish_on_commit
from core.services.post_transfer import post_transfer
from ledger.models import Account
from orders.models import Order
from payments.address_validation import normalize_payout_address
from payments.models import (
    Chain,
    MoneroOrderEscrow,
    MoneroOrderEscrowEvent,
)

XMR_ATOMIC_UNITS = 10**12
CALLBACK_CLOCK_SKEW = timedelta(minutes=5)


def _validate_callback_url() -> str:
    from urllib.parse import urlparse

    url = settings.MONERO_ESCROW_CALLBACK_URL
    parsed = urlparse(url)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ImproperlyConfigured(
            "MONERO_ESCROW_CALLBACK_URL must be an absolute URL without credentials."
        )
    is_onion_http = (
        parsed.scheme == "http"
        and parsed.hostname.endswith(".onion")
        and parsed.hostname in settings.ONION_HOSTS
    )
    is_https_host = (
        parsed.scheme == "https" and parsed.hostname in settings.ALLOWED_HOSTS
    )
    if not (is_onion_http or is_https_host):
        raise ImproperlyConfigured(
            "Monero escrow callbacks must use HTTPS on an allowed host or a configured onion host."
        )
    return url


@transaction.atomic
def start_monero_order_escrow(order_id: int, actor) -> MoneroOrderEscrow:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("buyer", "vendor__user")
        .get(pk=order_id)
    )
    if actor is None or order.buyer_id != actor.pk:
        raise PermissionDenied("Only the order's buyer can start Monero escrow.")
    if order.state != Order.State.DRAFT:
        raise ValidationError("Monero escrow can only fund a draft order.")
    if order.payment_method == Order.PaymentMethod.XMR_MULTISIG:
        escrow = MoneroOrderEscrow.objects.filter(order=order).first()
        if escrow is not None:
            return escrow
        raise ValidationError("The order's Monero escrow record is unavailable.")
    if order.payment_method != Order.PaymentMethod.LEDGER:
        raise ValidationError("The order already has a different payment method.")
    if not settings.MONERO_ESCROW_RELEASE_ADDRESS:
        raise ImproperlyConfigured(
            "MONERO_ESCROW_RELEASE_ADDRESS is required for multisig escrow."
        )
    normalize_payout_address(Chain.XMR, settings.MONERO_ESCROW_RELEASE_ADDRESS)
    _validate_callback_url()
    from payments.monero_escrow_gateway import gateway_configuration

    gateway_configuration()
    calculate_market_commission(order.total_amount)

    escrow = MoneroOrderEscrow.objects.create(
        order=order,
    )
    order.payment_method = Order.PaymentMethod.XMR_MULTISIG
    order.save(update_fields=("payment_method", "updated_at"))
    publish_on_commit(
        "monero_escrow_create",
        {"escrow_id": escrow.pk},
    )
    return escrow


@transaction.atomic
def request_monero_order_settlement(
    order: Order,
    *,
    released_amount: int,
    refunded_amount: int,
) -> MoneroOrderEscrow:
    escrow = MoneroOrderEscrow.objects.select_for_update().get(order=order)
    if (
        isinstance(released_amount, bool)
        or not isinstance(released_amount, int)
        or released_amount < 0
        or isinstance(refunded_amount, bool)
        or not isinstance(refunded_amount, int)
        or refunded_amount < 0
        or released_amount + refunded_amount != order.total_amount
    ):
        raise ValidationError("Monero settlement amounts must equal the order total.")
    if released_amount:
        calculate_market_commission(released_amount)
    if escrow.state == MoneroOrderEscrow.State.SETTLEMENT_PENDING:
        expected_action = (
            MoneroOrderEscrow.SettlementAction.PARTIAL
            if released_amount and refunded_amount
            else (
                MoneroOrderEscrow.SettlementAction.RELEASE
                if released_amount
                else MoneroOrderEscrow.SettlementAction.REFUND
            )
        )
        if (
            escrow.settlement_action == expected_action
            and escrow.settlement_release_base_units == released_amount
        ):
            return escrow
        raise ValidationError("A different Monero settlement is already pending.")
    if escrow.state != MoneroOrderEscrow.State.FUNDED:
        raise ValidationError("Only funded Monero escrows can be settled.")

    escrow.settlement_action = (
        MoneroOrderEscrow.SettlementAction.PARTIAL
        if released_amount and refunded_amount
        else (
            MoneroOrderEscrow.SettlementAction.RELEASE
            if released_amount
            else MoneroOrderEscrow.SettlementAction.REFUND
        )
    )
    escrow.settlement_release_base_units = released_amount
    escrow.state = MoneroOrderEscrow.State.SETTLEMENT_PENDING
    escrow.save(
        update_fields=(
            "settlement_action",
            "settlement_release_base_units",
            "state",
            "updated_at",
        )
    )
    publish_on_commit(
        "monero_escrow_settlement",
        {"escrow_id": escrow.pk},
    )
    apply_order_transition(order, "xmr_settlement_pending")
    order.save(update_fields=("state", "updated_at"))
    return escrow


@transaction.atomic
def request_monero_order_cancel(order: Order, reason: str) -> MoneroOrderEscrow:
    if reason not in {"buyer", "deadline"}:
        raise ValueError("Unsupported Monero escrow cancellation reason.")
    escrow = MoneroOrderEscrow.objects.select_for_update().get(order=order)
    if escrow.state == MoneroOrderEscrow.State.CANCELLATION_PENDING:
        if escrow.cancellation_reason == reason:
            return escrow
        raise ValidationError("Monero escrow cancellation is already pending.")
    if escrow.state not in {
        MoneroOrderEscrow.State.REQUESTED,
        MoneroOrderEscrow.State.AWAITING_SIGNERS,
        MoneroOrderEscrow.State.AWAITING_FUNDING,
    }:
        raise ValidationError(
            "This Monero escrow cannot be cancelled without settlement."
        )
    escrow.state = MoneroOrderEscrow.State.CANCELLATION_PENDING
    escrow.cancellation_reason = reason
    escrow.save(update_fields=("state", "cancellation_reason", "updated_at"))
    publish_on_commit("monero_escrow_cancel", {"escrow_id": escrow.pk})
    return escrow


def process_monero_order_escrow_job(escrow_id: int) -> None:
    from payments.monero_escrow_gateway import (
        create_remote_escrow,
        request_remote_cancel,
        request_remote_settlement,
    )

    escrow = MoneroOrderEscrow.objects.select_related(
        "order__vendor__user", "rate_quote"
    ).get(pk=escrow_id)
    if escrow.state == MoneroOrderEscrow.State.REQUESTED or (
        escrow.state == MoneroOrderEscrow.State.CANCELLATION_PENDING
        and not escrow.external_id
    ):
        remote_id = create_remote_escrow(
            order=escrow.order,
            callback_url=_validate_callback_url(),
        )
        with transaction.atomic():
            locked = MoneroOrderEscrow.objects.select_for_update().get(pk=escrow_id)
            if not locked.external_id:
                locked.external_id = remote_id
                if locked.state == MoneroOrderEscrow.State.REQUESTED:
                    locked.state = MoneroOrderEscrow.State.AWAITING_SIGNERS
                locked.save(update_fields=("external_id", "state", "updated_at"))
        return
    if escrow.state == MoneroOrderEscrow.State.SETTLEMENT_PENDING:
        request_remote_settlement(escrow=escrow, order=escrow.order)
        return
    if escrow.state == MoneroOrderEscrow.State.CANCELLATION_PENDING:
        request_remote_cancel(escrow=escrow, order=escrow.order)
        return
    if escrow.state in {
        MoneroOrderEscrow.State.AWAITING_SIGNERS,
        MoneroOrderEscrow.State.AWAITING_FUNDING,
        MoneroOrderEscrow.State.FUNDED,
        MoneroOrderEscrow.State.SETTLED,
    }:
        return
    raise ValidationError(f"Cannot process Monero escrow in {escrow.state} state.")


def verify_monero_escrow_callback(
    raw_body: bytes,
    timestamp_header: str,
    nonce: str,
    signature: str,
    *,
    now=None,
) -> bool:
    secret = settings.MONERO_ESCROW_GATEWAY_SECRET
    if (
        len(secret) < 32
        or not timestamp_header.isdigit()
        or len(timestamp_header) > 12
        or not nonce
        or len(nonce) > 128
        or len(signature) != 64
    ):
        return False
    now = now or timezone.now()
    timestamp = int(timestamp_header)
    if abs(now.timestamp() - timestamp) > CALLBACK_CLOCK_SKEW.total_seconds():
        return False
    message = b".".join((timestamp_header.encode(), nonce.encode(), raw_body))
    expected = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@transaction.atomic
def apply_monero_escrow_callback(payload: dict) -> bool:
    event_id = payload.get("event_id")
    order_id = payload.get("order_id")
    sequence = payload.get("sequence")
    event_type = payload.get("type")
    if (
        not isinstance(event_id, str)
        or not event_id
        or len(event_id) > 128
        or isinstance(order_id, bool)
        or not isinstance(order_id, int)
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence <= 0
        or not isinstance(event_type, str)
    ):
        raise ValidationError("Monero escrow callback has invalid event metadata.")
    if MoneroOrderEscrowEvent.objects.filter(event_id=event_id).exists():
        return False

    escrow = (
        MoneroOrderEscrow.objects.select_for_update()
        .select_related("order__buyer", "order__vendor__user", "rate_quote")
        .get(order_id=order_id)
    )
    if MoneroOrderEscrowEvent.objects.filter(event_id=event_id).exists():
        return False
    callback_escrow_id = payload.get("escrow_id")
    if (
        not isinstance(callback_escrow_id, str)
        or not callback_escrow_id
        or (escrow.external_id and callback_escrow_id != escrow.external_id)
    ):
        raise ValidationError("Monero escrow callback ID does not match the order.")
    if sequence != escrow.last_event_sequence + 1:
        raise ValidationError("Monero escrow callback sequence is out of order.")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValidationError("Monero escrow callback data must be an object.")

    if event_type == "ready":
        if escrow.state not in {
            MoneroOrderEscrow.State.REQUESTED,
            MoneroOrderEscrow.State.AWAITING_SIGNERS,
        }:
            raise ValidationError("Monero escrow is not awaiting participant setup.")
        address = data.get("address")
        if not isinstance(address, str):
            raise ValidationError("Monero escrow callback has no deposit address.")
        normalize_payout_address(Chain.XMR, address)
        quote = issue_xmr_rate_quote_for_base_amount(
            escrow.order.buyer,
            Chain.XMR,
            escrow.order.total_amount,
        )
        escrow.rate_quote = quote
        escrow.expected_amount_atomic = quote.amount_min_atomic
        escrow.external_id = callback_escrow_id
        escrow.deposit_address = address
        escrow.state = MoneroOrderEscrow.State.AWAITING_FUNDING
    elif event_type == "funded":
        cancellation_was_pending = (
            escrow.state == MoneroOrderEscrow.State.CANCELLATION_PENDING
        )
        previously_cancelled = escrow.state == MoneroOrderEscrow.State.CANCELLED
        if escrow.state not in {
            MoneroOrderEscrow.State.AWAITING_FUNDING,
            MoneroOrderEscrow.State.CANCELLATION_PENDING,
            MoneroOrderEscrow.State.CANCELLED,
        }:
            raise ValidationError("Monero escrow is not awaiting funding.")
        txid = data.get("transaction_id")
        amount_atomic = data.get("amount_atomic")
        confirmations = data.get("confirmations")
        if (
            not isinstance(txid, str)
            or not txid
            or len(txid) > 128
            or isinstance(amount_atomic, bool)
            or not isinstance(amount_atomic, int)
            or amount_atomic < escrow.expected_amount_atomic
            or isinstance(confirmations, bool)
            or not isinstance(confirmations, int)
            or confirmations < settings.MARKET_CHAIN_CONFIRMATIONS[Chain.XMR]
            or escrow.expected_amount_atomic <= 0
        ):
            raise ValidationError(
                "Monero funding callback has invalid confirmation data."
            )
        order = escrow.order
        cancelled_order = order.state in {Order.State.CANCELLED, Order.State.EXPIRED}
        refund_late_funding = (
            cancellation_was_pending or previously_cancelled or cancelled_order
        )
        if escrow.rate_quote is None or (
            timezone.now() >= escrow.rate_quote.locked_until and not refund_late_funding
        ):
            escrow.received_amount_atomic = amount_atomic
            escrow.state = MoneroOrderEscrow.State.REVIEW
            escrow.last_event_sequence = sequence
            escrow.save(
                update_fields=(
                    "received_amount_atomic",
                    "state",
                    "last_event_sequence",
                    "updated_at",
                )
            )
            MoneroOrderEscrowEvent.objects.create(
                escrow=escrow,
                event_id=event_id,
                sequence=sequence,
                event_type=event_type,
                payload=_sanitized_event_payload(payload),
            )
            return True
        if not refund_late_funding and order.state != Order.State.DRAFT:
            raise ValidationError("Only draft orders can be funded by Monero escrow.")
        if refund_late_funding and order.state not in {
            Order.State.DRAFT,
            Order.State.CANCELLED,
            Order.State.EXPIRED,
        }:
            raise ValidationError(
                "Late Monero funding cannot be reconciled in this order state."
            )
        escrow.received_amount_atomic = amount_atomic
        escrow.state = MoneroOrderEscrow.State.FUNDED
        escrow.cancellation_reason = ""
        if refund_late_funding:
            escrow.last_event_sequence = sequence
            escrow.save(
                update_fields=(
                    "received_amount_atomic",
                    "state",
                    "cancellation_reason",
                    "last_event_sequence",
                    "updated_at",
                )
            )
            MoneroOrderEscrowEvent.objects.create(
                escrow=escrow,
                event_id=event_id,
                sequence=sequence,
                event_type=event_type,
                payload=_sanitized_event_payload(payload),
            )
            request_monero_order_settlement(
                order,
                released_amount=0,
                refunded_amount=order.total_amount,
            )
            return True
        order.funded_at = timezone.now()
        apply_order_transition(order, "fund")
        order.save(update_fields=("state", "funded_at", "updated_at"))
    elif event_type == "settled":
        _apply_settled_callback(escrow, data)
    elif event_type == "cancelled":
        if (
            escrow.state != MoneroOrderEscrow.State.CANCELLATION_PENDING
            or data.get("no_funds") is not True
            or escrow.order.state != Order.State.DRAFT
        ):
            raise ValidationError("Monero escrow cannot be confirmed cancelled.")
        cancel_action = (
            "expire" if escrow.cancellation_reason == "deadline" else "cancel"
        )
        apply_order_transition(escrow.order, cancel_action)
        escrow.order.save(update_fields=("state", "updated_at"))
        escrow.state = MoneroOrderEscrow.State.CANCELLED
        escrow.cancellation_reason = ""
    elif event_type == "failed":
        if escrow.state in {
            MoneroOrderEscrow.State.SETTLED,
            MoneroOrderEscrow.State.CANCELLED,
        }:
            raise ValidationError("A terminal Monero escrow cannot fail.")
        escrow.state = MoneroOrderEscrow.State.REVIEW
    else:
        raise ValidationError("Unsupported Monero escrow callback event.")

    escrow.last_event_sequence = sequence
    escrow.save()
    MoneroOrderEscrowEvent.objects.create(
        escrow=escrow,
        event_id=event_id,
        sequence=sequence,
        event_type=event_type,
        payload=_sanitized_event_payload(payload),
    )
    return True


def _sanitized_event_payload(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
    allowed_fields = {
        "ready": ("address", "amount_atomic"),
        "funded": ("transaction_id", "amount_atomic", "confirmations"),
        "settled": ("action", "transaction_id", "amount_atomic", "confirmations"),
        "failed": ("reason",),
    }.get(payload.get("type"), ())
    return {
        "event_id": payload.get("event_id"),
        "order_id": payload.get("order_id"),
        "sequence": payload.get("sequence"),
        "type": payload.get("type"),
        "data": {key: data[key] for key in allowed_fields if key in data},
    }


def _apply_settled_callback(escrow: MoneroOrderEscrow, data: dict) -> None:
    if escrow.state != MoneroOrderEscrow.State.SETTLEMENT_PENDING:
        raise ValidationError("Monero escrow has no pending settlement.")
    action = data.get("action")
    transaction_id = data.get("transaction_id")
    amount_atomic = data.get("amount_atomic")
    confirmations = data.get("confirmations")
    if (
        action != escrow.settlement_action
        or not isinstance(transaction_id, str)
        or not transaction_id
        or len(transaction_id) > 128
        or isinstance(amount_atomic, bool)
        or not isinstance(amount_atomic, int)
        or amount_atomic <= 0
        or isinstance(confirmations, bool)
        or not isinstance(confirmations, int)
        or confirmations < settings.MARKET_CHAIN_CONFIRMATIONS[Chain.XMR]
    ):
        raise ValidationError(
            "Monero settlement callback has invalid transaction data."
        )
    if escrow.rate_quote is None:
        raise ValidationError("Monero escrow has no locked exchange-rate quote.")
    received_base_units = (
        amount_atomic * escrow.rate_quote.base_units_per_coin // XMR_ATOMIC_UNITS
    )
    order = escrow.order
    if received_base_units < order.total_amount:
        escrow.received_amount_atomic = amount_atomic
        escrow.settlement_transaction_id = transaction_id
        escrow.state = MoneroOrderEscrow.State.REVIEW
        return

    released = escrow.settlement_release_base_units or 0
    refunded = order.total_amount - released
    external, _ = Account.objects.get_or_create(
        kind=Account.Kind.EXTERNAL,
        owner=None,
    )
    if released:
        fee, net = calculate_market_commission(released)
        vendor_available, _ = Account.objects.get_or_create(
            kind=Account.Kind.VENDOR_AVAILABLE,
            owner=order.vendor.user,
        )
        market_fee, _ = Account.objects.get_or_create(
            kind=Account.Kind.MARKET_FEE,
            owner=None,
        )
        post_transfer(
            external,
            vendor_available,
            net,
            f"monero-order-{order.pk}-vendor",
            allow_external_source=True,
            order=order,
        )
        post_transfer(
            external,
            market_fee,
            fee,
            f"monero-order-{order.pk}-fee",
            allow_external_source=True,
            order=order,
        )
    if refunded:
        buyer_available, _ = Account.objects.get_or_create(
            kind=Account.Kind.USER_AVAILABLE,
            owner=order.buyer,
        )
        post_transfer(
            external,
            buyer_available,
            refunded,
            f"monero-order-{order.pk}-refund",
            allow_external_source=True,
            order=order,
        )

    transition = {
        MoneroOrderEscrow.SettlementAction.RELEASE: "xmr_release",
        MoneroOrderEscrow.SettlementAction.REFUND: "xmr_refund",
        MoneroOrderEscrow.SettlementAction.PARTIAL: "xmr_partial",
    }[escrow.settlement_action]
    apply_order_transition(order, transition)
    order.released_amount = released
    order.save(update_fields=("state", "released_amount", "updated_at"))
    escrow.received_amount_atomic = amount_atomic
    escrow.settlement_transaction_id = transaction_id
    escrow.state = MoneroOrderEscrow.State.SETTLED
    escrow.settled_at = timezone.now()
