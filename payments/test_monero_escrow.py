import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Listing
from core.services.create_vendor_profile import create_vendor_profile
from core.services.finalize import finalize
from core.services.monero_order_escrow import (
    apply_monero_escrow_callback,
    start_monero_order_escrow,
    verify_monero_escrow_callback,
)
from ledger.models import Account
from orders.models import Order
from payments.models import (
    Chain,
    MoneroOrderEscrow,
    MoneroOrderEscrowEvent,
    RateTick,
)


@pytest.fixture
def monero_order(db, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    buyer = User.objects.create_user(
        username="xmr-buyer",
        password="valid-test-password",
    )
    vendor_user = User.objects.create_user(
        username="xmr-vendor",
        password="valid-test-password",
    )
    vendor = create_vendor_profile(vendor_user)
    category = Category.objects.create(name="XMR category", slug="xmr-category")
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="XMR order item",
        description="Multisig test item",
        price=100_000_000,
        stock=1,
        is_active=True,
    )
    order = Order.objects.create(
        buyer=buyer,
        vendor=vendor,
        listing=listing,
        listing_title=listing.title,
        quantity=1,
        unit_price=listing.price,
        total_amount=listing.price,
        delivery_type=Order.DeliveryType.DIGITAL,
        delivery_lane=Order.DeliveryLane.DIGITAL,
    )
    now = timezone.now()
    RateTick.objects.create(
        chain=Chain.XMR,
        source="coinbase",
        base_units_per_coin=100_000_000,
        observed_at=now,
    )
    RateTick.objects.create(
        chain=Chain.XMR,
        source="kraken",
        base_units_per_coin=100_000_000,
        observed_at=now,
    )
    settings.MONERO_ESCROW_RELEASE_ADDRESS = "release-address"
    settings.MONERO_ESCROW_CALLBACK_URL = (
        "https://testserver/payments/monero-escrow/events/"
    )
    settings.MONERO_ESCROW_GATEWAY_URL = "https://signers.example"
    settings.MONERO_ESCROW_GATEWAY_ALLOWED_HOSTS = ["signers.example"]
    settings.MONERO_ESCROW_GATEWAY_SECRET = "x" * 48
    settings.ALLOWED_HOSTS = ["testserver"]
    return buyer, vendor_user, order


def _event(
    *,
    order_id: int,
    escrow_id: str,
    event_id: str,
    sequence: int,
    event_type: str,
    data: dict,
) -> dict:
    return {
        "event_id": event_id,
        "order_id": order_id,
        "escrow_id": escrow_id,
        "sequence": sequence,
        "type": event_type,
        "data": data,
    }


@pytest.mark.django_db
def test_monero_multisig_order_funding_and_release_credit_vendor_and_fee(
    monero_order,
) -> None:
    buyer, vendor_user, order = monero_order
    with (
        patch(
            "core.services.monero_order_escrow.normalize_payout_address",
            return_value="release-address",
        ),
        patch(
            "payments.monero_escrow_gateway.gateway_configuration",
            return_value=("https://signers.example", b"x" * 48),
        ),
        patch("core.services.monero_order_escrow.publish_on_commit"),
    ):
        escrow = start_monero_order_escrow(order.pk, buyer)

    assert escrow.state == MoneroOrderEscrow.State.REQUESTED
    assert escrow.expected_amount_atomic == 0
    order.refresh_from_db()
    assert order.payment_method == Order.PaymentMethod.XMR_MULTISIG

    with patch(
        "core.services.monero_order_escrow.normalize_payout_address",
        return_value="valid-multisig-address",
    ):
        apply_monero_escrow_callback(
            _event(
                order_id=order.pk,
                escrow_id="remote-escrow-1",
                event_id="event-ready",
                sequence=1,
                event_type="ready",
                data={"address": "valid-multisig-address"},
            )
        )

    escrow.refresh_from_db()
    assert escrow.state == MoneroOrderEscrow.State.AWAITING_FUNDING
    assert escrow.expected_amount_atomic == 10**12
    assert escrow.rate_quote is not None

    apply_monero_escrow_callback(
        _event(
            order_id=order.pk,
            escrow_id="remote-escrow-1",
            event_id="event-funded",
            sequence=2,
            event_type="funded",
            data={
                "transaction_id": "funding-tx",
                "amount_atomic": 10**12,
                "confirmations": 10,
            },
        )
    )
    order.refresh_from_db()
    escrow.refresh_from_db()
    assert order.state == Order.State.FUNDED
    assert escrow.state == MoneroOrderEscrow.State.FUNDED
    assert not order.buyer.ledger_accounts.filter(
        kind=Account.Kind.USER_ESCROW,
        entries__amount__gt=0,
    ).exists()

    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() - timedelta(seconds=1)
    order.save(update_fields=("state", "finalize_at", "updated_at"))
    with patch("core.services.monero_order_escrow.publish_on_commit"):
        finalize(order.pk)

    order.refresh_from_db()
    escrow.refresh_from_db()
    assert order.state == Order.State.SETTLEMENT_PENDING
    assert escrow.state == MoneroOrderEscrow.State.SETTLEMENT_PENDING

    apply_monero_escrow_callback(
        _event(
            order_id=order.pk,
            escrow_id="remote-escrow-1",
            event_id="event-settled",
            sequence=3,
            event_type="settled",
            data={
                "action": "release",
                "transaction_id": "release-tx",
                "amount_atomic": 10**12,
                "confirmations": 10,
            },
        )
    )

    order.refresh_from_db()
    escrow.refresh_from_db()
    vendor_available = Account.objects.get(
        kind=Account.Kind.VENDOR_AVAILABLE,
        owner=vendor_user,
    )
    market_fee = Account.objects.get(
        kind=Account.Kind.MARKET_FEE,
        owner=None,
    )
    assert order.state == Order.State.FINALIZED
    assert order.released_amount == order.total_amount
    assert escrow.state == MoneroOrderEscrow.State.SETTLED
    assert escrow.settlement_transaction_id == "release-tx"
    assert vendor_available.balance == 97_000_000
    assert market_fee.balance == 3_000_000
    assert MoneroOrderEscrowEvent.objects.filter(escrow=escrow).count() == 3


@pytest.mark.django_db
def test_monero_escrow_callback_signature_is_timestamped_and_idempotent(
    settings,
) -> None:
    secret = "callback-secret-that-is-long-enough-123"
    settings.MONERO_ESCROW_GATEWAY_SECRET = secret
    now = timezone.now()
    timestamp = str(int(now.timestamp()))
    nonce = "one-time-gateway-request"
    body = json.dumps({"event_id": "event-1"}).encode()
    signature = hmac.new(
        secret.encode(),
        b".".join((timestamp.encode(), nonce.encode(), body)),
        hashlib.sha256,
    ).hexdigest()

    assert verify_monero_escrow_callback(
        body,
        timestamp,
        nonce,
        signature,
        now=now,
    )
    assert not verify_monero_escrow_callback(
        body,
        timestamp,
        nonce,
        "0" * 64,
        now=now,
    )
    assert not verify_monero_escrow_callback(
        body,
        str(int((now - timedelta(minutes=6)).timestamp())),
        nonce,
        signature,
        now=now,
    )
