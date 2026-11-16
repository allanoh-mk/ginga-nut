from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Listing, VendorProfile
from core.services.create_vendor_profile import create_vendor_profile
from orders.models import Dispute, Order, PublicRuling
from payments.models import (
    Chain,
    Deposit,
    DepositAddress,
    PayoutAddress,
    PayoutAddressChallenge,
)

APP_PAGE_LIMIT = 40 * 1024
STYLEGUIDE_LIMIT = 20 * 1024


class AccessibilityMarkup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.labelled_ids = set()
        self.controls = []
        self.fieldset_depth = 0
        self.fieldsets_without_legend = 0
        self.focusable = []
        self.positive_tabindex = []
        self.aria_hidden_focusable = []
        self.flash_live = False
        self.status_text = []
        self.external_assets = []
        self._label_open = False
        self._status_depth = 0
        self._status_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "img", "link"}:
            for attr in ("src", "href"):
                target = attrs.get(attr, "")
                if target.startswith(("http://", "https://", "//")):
                    self.external_assets.append(target)
        if tag == "label" and attrs.get("for"):
            self.labelled_ids.add(attrs["for"])
        if tag == "fieldset":
            self.fieldset_depth += 1
            self.fieldsets_without_legend += 1
        if tag == "legend" and self.fieldset_depth:
            self.fieldsets_without_legend -= 1
        if tag in {"input", "select", "textarea"}:
            if tag != "input" or attrs.get("type", "text") not in {
                "hidden",
                "submit",
                "button",
                "reset",
            }:
                self.controls.append(
                    (
                        attrs.get("id"),
                        attrs.get("aria-label"),
                        attrs.get("aria-labelledby"),
                    )
                )
        if tag in {"a", "button", "input", "select", "textarea"}:
            if tag != "input" or attrs.get("type", "text") not in {
                "hidden",
                "submit",
                "button",
                "reset",
            }:
                if tag != "a" or attrs.get("href"):
                    self.focusable.append((tag, attrs))
                    if (
                        attrs.get("tabindex", "0").isdigit()
                        and int(attrs.get("tabindex", "0")) > 0
                    ):
                        self.positive_tabindex.append(attrs)
                    if attrs.get("aria-hidden") == "true":
                        self.aria_hidden_focusable.append(attrs)
        if attrs.get("aria-live") == "polite":
            self.flash_live = True
        if "status-pill" in attrs.get("class", "").split():
            self._status_depth = 1
            self._status_parts = []
        elif self._status_depth:
            self._status_depth += 1

    def handle_endtag(self, tag):
        if tag == "fieldset" and self.fieldset_depth:
            self.fieldset_depth -= 1
        if self._status_depth:
            self._status_depth -= 1
            if self._status_depth == 0:
                self.status_text.append("".join(self._status_parts).strip())

    def handle_data(self, data):
        if self._status_depth:
            self._status_parts.append(data)


def assert_accessible_markup(content):
    parser = AccessibilityMarkup()
    parser.feed(content.decode())
    assert parser.flash_live
    assert parser.fieldsets_without_legend == 0
    assert parser.focusable and parser.focusable[0][0] == "a"
    assert "skip-link" in parser.focusable[0][1].get("class", "").split()
    assert not parser.positive_tabindex
    assert not parser.aria_hidden_focusable
    assert all(
        aria_label or labelledby or (control_id and control_id in parser.labelled_ids)
        for control_id, aria_label, labelledby in parser.controls
    )
    assert all(parser.status_text)


@pytest.fixture
def page_world(db, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    buyer = User.objects.create_user(username="page_buyer", password="unused")
    vendor_user = User.objects.create_user(username="page_vendor", password="unused")
    vendor = create_vendor_profile(vendor_user)
    vendor.is_approved = True
    vendor.save(update_fields=("is_approved",))
    category = Category.objects.create(name="Produce", slug="produce")
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="Seasonal basket",
        description="A sample listing for rendered page checks.",
        price=100_000_000,
        stock=4,
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
    )
    dispute = Dispute.objects.create(
        order=order,
        filed_by=buyer,
        reason="Delivery was not received.",
    )
    ruling = PublicRuling.objects.create(
        dispute=dispute,
        amount_band="1.00–1.00 base",
        category=category,
        outcome=PublicRuling.Outcome.REFUND,
        reason="The delivery record supports a refund.",
    )
    address = DepositAddress.objects.create(
        user=buyer,
        chain=Chain.BTC,
        address="bc1qexampledepositaddress",
    )
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="page-test-deposit",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    payout = PayoutAddress.objects.create(
        user=buyer,
        chain=Chain.TRC20,
        address="TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
        label="Main address",
        available_after=timezone.now() - timedelta(days=1),
    )
    challenge = PayoutAddressChallenge.objects.create(
        user=buyer,
        payout_address=payout,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    return {
        "buyer": buyer,
        "category": category,
        "listing": listing,
        "order": order,
        "ruling": ruling,
        "deposit": deposit,
        "challenge": challenge,
    }


def assert_page(response, *, limit=APP_PAGE_LIMIT):
    assert response.status_code == 200
    assert len(response.content) < limit
    assert response.content.count(b"<h1") == 1
    assert b"<title>" in response.content
    assert_accessible_markup(response.content)


def assert_page_status(response, *, status, limit=APP_PAGE_LIMIT):
    assert response.status_code == status
    assert len(response.content) < limit
    assert response.content.count(b"<h1") == 1
    assert b"<title>" in response.content
    assert_accessible_markup(response.content)


@pytest.mark.django_db
def test_current_page_wave_renders_within_size_limit(page_world, settings):
    settings.ALLOW_FAKE_PROVIDERS = True
    anonymous = Client()
    buyer = page_world["buyer"]
    signed_in = Client()
    signed_in.force_login(buyer)

    public_paths = [
        reverse("home"),
        reverse("how-it-works"),
        reverse("ops:canary"),
        reverse("orders:public-rulings"),
        reverse("orders:public-ruling", args=(page_world["ruling"].pk,)),
        reverse("ops:reserves"),
        reverse("catalog:categories"),
        reverse("catalog:category", args=(page_world["category"].slug,)),
        reverse("catalog:search"),
        reverse("catalog:listing", args=(page_world["listing"].pk,)),
        reverse("catalog:cart"),
        reverse("ops:styleguide"),
    ]
    for path in public_paths:
        response = anonymous.get(path)
        assert_page(
            response,
            limit=STYLEGUIDE_LIMIT
            if path == reverse("ops:styleguide")
            else APP_PAGE_LIMIT,
        )

    auth_paths = [
        reverse("accounts:register"),
        reverse("accounts:login"),
        reverse("accounts:recovery_login"),
    ]
    for path in auth_paths:
        assert_page(anonymous.get(path))

    session = signed_in.session
    session["pending_pgp_auth"] = {
        "user_id": buyer.pk,
        "mode": "enroll",
        "challenge": "page-size-challenge",
        "created_at": int(timezone.now().timestamp()),
        "attempts": 0,
    }
    session.save()
    assert_page(signed_in.get(reverse("accounts:pgp_auth")))

    buyer.pgp_public_key = "sample key"
    buyer.pgp_fingerprint = "SAMPLE"
    buyer.save(update_fields=("pgp_public_key", "pgp_fingerprint"))
    session = signed_in.session
    session["pending_pgp_auth"] = {
        "user_id": buyer.pk,
        "mode": "login",
        "challenge": "page-size-challenge",
        "created_at": int(timezone.now().timestamp()),
        "attempts": 0,
    }
    session.save()
    assert_page(signed_in.get(reverse("accounts:pgp_auth")))
    signed_in.post(reverse("accounts:regenerate_recovery_codes"))
    assert_page(signed_in.get(reverse("accounts:pgp_auth")))
    assert_page(signed_in.get(reverse("accounts:logout_confirm")))
    assert_page(signed_in.get(reverse("accounts:balance")))
    assert_page(signed_in.get(reverse("accounts:deposits")))
    assert_page(signed_in.get(reverse("accounts:deposit_history")))
    assert_page(
        signed_in.get(
            reverse("accounts:deposit_quote_convert", args=(page_world["deposit"].pk,))
        )
    )
    assert_page(signed_in.get(reverse("accounts:withdrawals")))
    assert_page(signed_in.get(reverse("accounts:payout_addresses")))
    assert_page(
        signed_in.get(
            reverse(
                "accounts:payout_address_verify", args=(page_world["challenge"].pk,)
            )
        )
    )

    session = signed_in.session
    session["market_cart"] = {str(page_world["listing"].pk): 1}
    session.save()
    assert_page(signed_in.get(reverse("catalog:cart")))
    assert_page(signed_in.get(reverse("catalog:cart_checkout")))

    session = signed_in.session
    session["order_created_ids"] = [page_world["order"].pk]
    session.save()
    assert_page(signed_in.get(reverse("catalog:order_created")))
    print("page size checks passed")


@pytest.mark.django_db
def test_vendor_ops_error_and_paused_wave_renders_within_size_limit(
    page_world, settings
):
    settings.ALLOW_FAKE_PROVIDERS = True
    vendor_profile = page_world["listing"].vendor
    now = timezone.now()
    for state, photo in (
        (Order.State.FUNDED, ""),
        (Order.State.ACCEPTED, ""),
        (Order.State.PACKED, "orders/pack/preview.jpg"),
    ):
        Order.objects.create(
            buyer=page_world["buyer"],
            vendor=vendor_profile,
            listing=page_world["listing"],
            listing_title=page_world["listing"].title,
            quantity=1,
            unit_price=page_world["listing"].price,
            total_amount=page_world["listing"].price,
            state=state,
            funded_at=now,
            expires_at=now + timedelta(hours=1),
            pack_photo=photo,
        )
    vendor = Client()
    vendor.force_login(vendor_profile.user)
    for path in (
        reverse("catalog:vendor-dashboard"),
        reverse("catalog:vendor-order-queue"),
        reverse("catalog:vendor-payouts"),
        reverse("catalog:vendor-edit-listing", args=(page_world["listing"].pk,)),
        reverse("catalog:vendor-delete-listing", args=(page_world["listing"].pk,)),
        reverse("catalog:vendor-create-listing"),
    ):
        assert_page(vendor.get(path))
    assert_page(
        Client().get(
            reverse(
                "catalog:vendor-public-profile", args=(vendor_profile.user.username,)
            )
        )
    )

    admin_user = User.objects.create_superuser(username="page_admin", password="unused")
    pending_user = User.objects.create_user(username="pending_maker", password="unused")
    create_vendor_profile(pending_user)
    pending_listing = Listing.objects.create(
        vendor=vendor_profile,
        category=page_world["category"],
        title="Pending maker sample",
        description="A listing waiting for maker review.",
        price=100,
        stock=2,
        is_active=True,
        is_approved=False,
    )
    open_order = Order.objects.create(
        buyer=page_world["buyer"],
        vendor=vendor_profile,
        listing=page_world["listing"],
        listing_title=page_world["listing"].title,
        quantity=1,
        unit_price=page_world["listing"].price,
        total_amount=page_world["listing"].price,
        state=Order.State.DISPUTED,
    )
    open_dispute = Dispute.objects.create(
        order=open_order,
        filed_by=page_world["buyer"],
        reason="Delivery needs review.",
    )
    admin = Client()
    admin.force_login(admin_user)
    admin_paths = (
        reverse("ops:dashboard"),
        reverse("ops:reserves"),
        reverse("ops:order-list"),
        reverse("ops:withdrawal-approval-queue"),
        reverse("ops:health-page"),
        reverse("orders:dispute-queue"),
        reverse("orders:review-dispute", args=(open_dispute.pk,)),
        reverse("catalog:vendor-approval-queue"),
        reverse("catalog:maker-approval-queue"),
    )
    for path in admin_paths:
        assert_page(admin.get(path))
    pending_profile = VendorProfile.objects.get(user=pending_user)
    assert (
        admin.post(
            reverse("catalog:vendor-approve", args=(pending_profile.pk,))
        ).status_code
        == 302
    )
    assert (
        admin.post(
            reverse("catalog:maker-approve", args=(pending_listing.pk,))
        ).status_code
        == 302
    )
    assert_page(admin.get(reverse("catalog:maker-approval-queue")))

    public = Client()
    for path, status in (
        (reverse("error-400"), 400),
        (reverse("error-403"), 403),
        (reverse("error-404"), 404),
        (reverse("error-500"), 500),
        (reverse("paused-new-orders"), 503),
        (reverse("paused-withdrawals"), 503),
        (reverse("paused-digital-listings"), 503),
    ):
        assert_page_status(public.get(path), status=status)


@pytest.mark.django_db
def test_vendor_application_and_bond_state_renders(page_world):
    applicant = User.objects.create_user(
        username="new_vendor_applicant", password="unused"
    )
    client = Client()
    client.force_login(applicant)
    assert_page(client.get(reverse("catalog:vendor-dashboard")))
    response = client.post(reverse("catalog:vendor-dashboard"), follow=True)
    assert_page(response)
    assert b"awaiting admin approval" in response.content
    response = client.post(
        reverse("catalog:vendor-bond"),
        {"amount_base_units": "100"},
        follow=True,
    )
    assert_page(response)
    assert b"Available balance is too low" in response.content


@pytest.mark.django_db
def test_dark_theme_and_styleguide_assets_are_local(page_world):
    stylesheet = (
        Path(__file__).resolve().parents[1] / "static/css/site.css"
    ).read_text()
    assert "color-scheme: dark" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "prefers-color-scheme" not in stylesheet
    assert "outline: none" not in stylesheet
    response = Client().get(reverse("ops:styleguide"))
    assert_page(response, limit=STYLEGUIDE_LIMIT)
    parser = AccessibilityMarkup()
    parser.feed(response.content.decode())
    assert not parser.external_assets
