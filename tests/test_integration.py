import re
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from catalog.models import Category, Listing
from core.services.accept import accept
from core.services.create_order import create_order
from core.services.create_vendor_profile import create_vendor_profile
from core.services.finalize import finalize
from core.services.fund_order import fund_order
from core.services.get_ledger_account import get_ledger_account
from core.services.pack_order import pack_order
from core.services.post_transfer import post_transfer
from core.services.process_withdrawal import process_withdrawal
from ledger.models import Account
from orders.models import Order
from payments.models import Chain, PayoutAddress, Withdrawal

PASSWORD = "a-very-long-unique-password-8492"
POD_TOKEN_PATTERN = re.compile(rb"<output>([^<]+)</output>")


@pytest.fixture(autouse=True)
def integration_settings(settings, tmp_path):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.MEDIA_ROOT = tmp_path


def register_and_login(client: Client, username: str) -> User:
    with patch(
        "accounts.views.verify_openpgp_signature", return_value="TESTFINGERPRINT"
    ):
        response = client.post(
            reverse("accounts:register"),
            {
                "username": username,
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )
        assert response.status_code == 302
        assert response.url == reverse("accounts:pgp_auth")

        response = client.post(
            reverse("accounts:pgp_auth"),
            {
                "public_key": "test public key",
                "signature": "test enrollment signature",
            },
        )
        assert response.status_code == 200
        user = User.objects.get(username=username)
        assert user.pgp_public_key == "test public key"

        client.post(reverse("accounts:logout"))
        with patch("accounts.views.authenticate_user", return_value=user):
            response = client.post(
                reverse("accounts:login"),
                {"username": username, "password": PASSWORD},
            )
        assert response.status_code == 302
        with patch(
            "accounts.views.verify_openpgp_signature", return_value="TESTFINGERPRINT"
        ):
            response = client.post(
                reverse("accounts:pgp_auth"),
                {"signature": "test login signature"},
            )
        assert response.status_code == 302
    return user


def image_upload() -> SimpleUploadedFile:
    content = BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(content, format="PNG")
    return SimpleUploadedFile(
        "product.png", content.getvalue(), content_type="image/png"
    )


def fund_from_external(order: Order, buyer: User) -> None:
    external, _ = Account.objects.get_or_create(kind=Account.Kind.EXTERNAL, owner=None)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer)
    post_transfer(
        external,
        available,
        order.total_amount,
        f"integration-funding-{order.pk}",
        allow_external_source=True,
    )


def deliver_order(
    buyer_client: Client,
    vendor_client: Client,
    order: Order,
    vendor: User,
) -> None:
    accept(order.pk, vendor)
    pack_order(order.pk, vendor, image_upload())
    response = vendor_client.post(
        reverse("orders:dispatch", args=(order.pk,)),
        {"courier_reference": "integration-courier-1"},
    )
    assert response.status_code == 302
    response = vendor_client.get(response.url)
    token_match = POD_TOKEN_PATTERN.search(response.content)
    assert token_match is not None
    response = buyer_client.post(
        reverse("orders:deliver", args=(order.pk,)),
        {"token": token_match.group(1).decode()},
    )
    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.DELIVERED
    finalize(order.pk, now=order.finalize_at + timedelta(seconds=1))
    order.refresh_from_db()
    assert order.state == Order.State.FINALIZED


@pytest.mark.django_db
def test_buyer_registration_search_checkout_fulfillment_and_review():
    buyer_client = Client()
    buyer = register_and_login(buyer_client, "journey-buyer")
    vendor = User.objects.create_user(username="journey-vendor")
    vendor_profile = create_vendor_profile(vendor)
    vendor_profile.is_approved = True
    vendor_profile.save(update_fields=("is_approved",))
    category = Category.objects.create(name="Journey items", slug="journey-items")
    listing = Listing.objects.create(
        vendor=vendor_profile,
        category=category,
        title="Blue journey item",
        description="A searchable integration product.",
        price=100_000_000,
        stock=2,
        is_active=True,
    )

    response = buyer_client.get(reverse("catalog:search"), {"q": "journey"})
    assert response.status_code == 200
    assert b"Blue journey item" in response.content
    assert (
        buyer_client.get(reverse("catalog:listing", args=(listing.pk,))).status_code
        == 200
    )

    response = buyer_client.post(
        reverse("catalog:checkout", args=(listing.pk,)),
        {
            "quantity": 1,
            "shipping_address": "12 Market Street",
            "shipping_phone": "+254700000000",
        },
    )
    assert response.status_code == 302
    order = Order.objects.get(buyer=buyer, listing=listing)
    listing.refresh_from_db()
    assert listing.stock == 1
    fund_from_external(order, buyer)
    fund_order(order.pk, buyer)

    vendor_client = Client()
    vendor_client.force_login(vendor)
    assert b"Order funded" in vendor_client.get(reverse("core:notifications")).content
    deliver_order(buyer_client, vendor_client, order, vendor)

    response = buyer_client.post(
        reverse("orders:submit-review", args=(order.pk,)),
        {"rating": "5", "comment": "Excellent integration item"},
    )
    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.average_rating == 5
    assert listing.review_count == 1


@pytest.mark.django_db
def test_vendor_application_listing_order_and_withdrawal_journey(settings):
    vendor_client = Client()
    vendor = register_and_login(vendor_client, "journey-listing-vendor")
    response = vendor_client.post(reverse("catalog:vendor-dashboard"))
    assert response.status_code == 302

    profile = vendor.vendor_profile
    staff = User.objects.create_superuser(username="journey-staff", password=PASSWORD)
    staff_client = Client()
    staff_client.force_login(staff)
    approval_response = staff_client.post(
        reverse("catalog:vendor-approve", args=(profile.pk,))
    )
    assert approval_response.status_code == 302
    profile.refresh_from_db()
    assert profile.is_approved
    category = Category.objects.create(name="Vendor journey", slug="vendor-journey")
    response = vendor_client.post(
        reverse("catalog:vendor-create-listing"),
        {
            "category": category.pk,
            "title": "Vendor journey listing",
            "description": "Created through the vendor listing form.",
            "price": 100_000_000,
            "stock": 1,
            "is_active": "on",
            "shipping_required": "on",
            "image": image_upload(),
        },
    )
    assert response.status_code == 302
    listing = Listing.objects.get(vendor=profile)
    assert listing.image
    public_listing = vendor_client.get(
        reverse("catalog:search"),
        {"q": "Vendor journey listing"},
    )
    assert public_listing.status_code == 200
    assert b"Vendor journey listing" in public_listing.content

    buyer = User.objects.create_user(username="journey-vendor-buyer")
    order = create_order(
        buyer=buyer,
        listing_id=listing.pk,
        quantity=1,
        shipping_address="1 Buyer Road",
        shipping_phone="+254700000001",
    )
    fund_from_external(order, buyer)
    fund_order(order.pk, buyer)
    buyer_client = Client()
    buyer_client.force_login(buyer)
    deliver_order(buyer_client, vendor_client, order, vendor)

    payout = PayoutAddress.objects.create(
        user=vendor,
        chain=Chain.BTC,
        address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        label="Integration destination",
        available_after=timezone.now() - timedelta(days=1),
        verified_at=timezone.now(),
    )
    settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = 1
    settings.MARKET_WITHDRAWAL_MAX_HOURLY_BASE_UNITS = 1
    settings.MARKET_WITHDRAWAL_MAX_DAILY_BASE_UNITS = 1
    vendor_balance = get_ledger_account(Account.Kind.VENDOR_AVAILABLE, owner=vendor)
    assert vendor_balance.balance > 0

    with (
        patch(
            "core.services.request_withdrawal.get_chain_provider"
        ) as request_provider,
    ):
        request_provider.return_value.supports_withdrawals = True
        request_provider.return_value.supports_withdrawal = True
        withdrawal_response = vendor_client.post(
            reverse("accounts:withdrawals"),
            {
                "payout_address": payout.pk,
                "amount": vendor_balance.balance,
                "idempotency_key": "vendor-journey-withdrawal",
            },
        )
    assert withdrawal_response.status_code == 302
    withdrawal = Withdrawal.objects.get(user=vendor)
    assert withdrawal.state == Withdrawal.State.MANUAL_APPROVAL

    with (
        patch("core.services.approve_withdrawal.publish_on_commit"),
        patch("core.services.process_withdrawal.get_chain_provider") as get_provider,
    ):
        provider = get_provider.return_value
        provider.supports_withdrawals = True
        provider.supports_withdrawal = True
        provider.send_withdrawal.return_value = "integration-provider-reference"

        approval_response = staff_client.post(
            reverse("ops:withdrawal-approve", args=(withdrawal.pk,))
        )
        assert approval_response.status_code == 302
        completed = process_withdrawal(withdrawal)
    assert completed.state == Withdrawal.State.COMPLETED
    assert completed.provider_reference == "integration-provider-reference"
