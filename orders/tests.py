from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, connections
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from catalog.models import Category, Listing
from core.services.accept import accept
from core.services.cancel_order import cancel_order
from core.services.create_vendor_profile import create_vendor_profile
from core.services.dispatch_order import POD_TOKEN_LIFETIME, dispatch_order
from core.services.expire_funding import expire_funding
from core.services.extend_finalize import extend_finalize
from core.services.finalize import finalize
from core.services.fund_order import fund_order
from core.services.get_ledger_account import get_ledger_account
from core.services.open_dispute import open_dispute
from core.services.order_transitions import ORDER_TRANSITIONS, transition_target
from core.services.pack_order import pack_order
from core.services.post_transfer import post_transfer
from core.services.record_delivery import record_delivery
from core.services.reject import reject
from core.services.rule_dispute import rule_dispute
from core.services.submit_dispute_evidence import submit_dispute_evidence
from ledger.models import Account, LedgerEntry
from orders.models import (
    City,
    DeliveryZone,
    Dispute,
    DisputeEvidence,
    Order,
    PublicRuling,
)
from orders.uploads import strip_image_metadata


@pytest.fixture(autouse=True)
def temporary_private_storage(settings, tmp_path):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def participants(db):
    buyer = User.objects.create_user(username="order_buyer", password="unused")
    vendor_user = User.objects.create_user(username="order_vendor", password="unused")
    vendor = create_vendor_profile(vendor_user)
    city = City.objects.create(name="Nairobi", slug="nairobi")
    zone = DeliveryZone.objects.create(city=city, name="Central")
    category = Category.objects.create(name="Home", slug="home")
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="Ceramic cup",
        description="A cup.",
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
        delivery_lane=Order.DeliveryLane.CITY,
        delivery_zone=zone,
        shipping_address="12 Market Street",
        shipping_phone="+254700000000",
    )
    return buyer, vendor_user, vendor, city, zone, category, listing, order


def image_upload(name: str = "customer-name.png") -> SimpleUploadedFile:
    content = BytesIO()
    Image.new("RGB", (4, 4), color="green").save(content, format="PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


def evidence_upload(name: str = "private-evidence.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name, b"%PDF-1.4 private evidence", content_type="application/pdf"
    )


def test_strip_image_metadata_removes_jpeg_exif() -> None:
    exif = Image.Exif()
    exif[0x010E] = "private camera note"
    content = BytesIO()
    Image.new("RGB", (4, 4), color="green").save(
        content,
        format="JPEG",
        exif=exif,
    )
    upload = SimpleUploadedFile(
        "private.jpg",
        content.getvalue(),
        content_type="image/jpeg",
    )

    sanitized = strip_image_metadata(upload)

    with Image.open(sanitized) as image:
        assert image.getexif() == {}


def test_strip_image_metadata_preserves_animated_webp() -> None:
    content = BytesIO()
    Image.new("RGB", (4, 4), color="green").save(
        content,
        format="WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (4, 4), color="blue")],
        duration=100,
        loop=0,
    )
    upload = SimpleUploadedFile(
        "animation.webp",
        content.getvalue(),
        content_type="image/webp",
    )

    sanitized = strip_image_metadata(upload)

    with Image.open(sanitized) as image:
        assert image.n_frames == 2
        assert "exif" not in image.info


@pytest.mark.django_db
def test_order_contact_detail_is_not_cached(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    client.force_login(buyer)

    response = client.get(reverse("orders:detail", args=(order.pk,)))

    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    assert "private" in response["Cache-Control"]


def fund_test_order(buyer: User, order: Order) -> Order:
    external, _ = Account.objects.get_or_create(
        kind=Account.Kind.EXTERNAL,
        owner=None,
    )
    Account.objects.get_or_create(kind=Account.Kind.MARKET_FEE, owner=None)
    Account.objects.get_or_create(kind=Account.Kind.TREASURY, owner=None)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer)
    post_transfer(
        external,
        available,
        order.total_amount,
        f"test-order-funding-{order.pk}",
        allow_external_source=True,
    )
    return fund_order(order.pk, buyer)


@pytest.mark.django_db
def test_delivery_zones_are_scoped_to_city(participants) -> None:
    _, _, _, _city, zone, *_ = participants
    other_city = City.objects.create(name="Mombasa", slug="mombasa")
    other_zone = DeliveryZone.objects.create(city=other_city, name="Central")

    assert str(zone) == "Nairobi: Central"
    assert str(other_zone) == "Mombasa: Central"
    assert zone.pk != other_zone.pk


@pytest.mark.django_db
def test_order_transition_table_accepts_only_listed_state_action_pairs() -> None:
    states = [state for state, _ in Order.State.choices]
    actions = {action for _, action in ORDER_TRANSITIONS}
    actions.add("unknown")
    expected = {
        (Order.State.DRAFT, "fund"): Order.State.FUNDED,
        (Order.State.DRAFT, "expire"): Order.State.EXPIRED,
        (Order.State.DRAFT, "cancel"): Order.State.CANCELLED,
        (Order.State.DRAFT, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
        (Order.State.FUNDED, "accept"): Order.State.ACCEPTED,
        (Order.State.FUNDED, "reject"): Order.State.REFUNDED,
        (Order.State.FUNDED, "expire_funding"): Order.State.REFUNDED,
        (Order.State.FUNDED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
        (Order.State.ACCEPTED, "pack"): Order.State.PACKED,
        (Order.State.ACCEPTED, "digital_delivery"): Order.State.DELIVERED,
        (Order.State.PACKED, "dispatch"): Order.State.DISPATCHED,
        (Order.State.DISPATCHED, "record_delivery"): Order.State.DELIVERED,
        (Order.State.DISPATCHED, "open_dispute"): Order.State.DISPUTED,
        (Order.State.DELIVERED, "open_dispute"): Order.State.DISPUTED,
        (Order.State.DELIVERED, "finalize"): Order.State.FINALIZED,
        (
            Order.State.DELIVERED,
            "xmr_settlement_pending",
        ): Order.State.SETTLEMENT_PENDING,
        (Order.State.DISPUTED, "finalize"): Order.State.FINALIZED,
        (
            Order.State.DISPUTED,
            "xmr_settlement_pending",
        ): Order.State.SETTLEMENT_PENDING,
        (Order.State.DISPUTED, "refund"): Order.State.REFUNDED,
        (Order.State.DISPUTED, "partial"): Order.State.PARTIAL,
        (Order.State.SETTLEMENT_PENDING, "xmr_release"): Order.State.FINALIZED,
        (Order.State.SETTLEMENT_PENDING, "xmr_refund"): Order.State.REFUNDED,
        (Order.State.SETTLEMENT_PENDING, "xmr_partial"): Order.State.PARTIAL,
        (
            Order.State.CANCELLED,
            "xmr_settlement_pending",
        ): Order.State.SETTLEMENT_PENDING,
        (Order.State.EXPIRED, "xmr_settlement_pending"): Order.State.SETTLEMENT_PENDING,
    }

    assert expected == ORDER_TRANSITIONS
    for (state, action), target in ORDER_TRANSITIONS.items():
        assert transition_target(state, action) == target
    for state in states:
        for action in actions:
            if (state, action) not in ORDER_TRANSITIONS:
                with pytest.raises(ValidationError, match="Illegal order transition"):
                    transition_target(state, action)


@pytest.mark.django_db
def test_fund_order_is_idempotent_for_the_same_order_and_buyer(participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)

    first = fund_order(order.pk, buyer)
    second = fund_order(order.pk, buyer)

    assert first.state == second.state == Order.State.FUNDED
    assert LedgerEntry.objects.filter(ref=f"order-fund-{order.pk}").count() == 2
    assert LedgerEntry.objects.filter(order=order).count() == 2


@pytest.mark.django_db
def test_vendor_accepts_and_rejects_only_funded_orders(participants) -> None:
    buyer, vendor_user, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)

    accepted = accept(order.pk, vendor_user)
    assert accepted.state == Order.State.ACCEPTED

    with pytest.raises(ValidationError, match="Illegal order transition"):
        reject(order.pk, vendor_user)

    order.refresh_from_db()
    order.state = Order.State.FUNDED
    order.save(update_fields=("state",))
    rejected = reject(order.pk, vendor_user)
    assert rejected.state == Order.State.REFUNDED
    assert (
        get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer).balance
        == order.total_amount
    )
    assert get_ledger_account(Account.Kind.USER_ESCROW, owner=buyer).balance == 0


@pytest.mark.django_db
def test_funding_expiry_handles_draft_and_funded_deadlines(participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    expired_draft = expire_funding(order.pk, now=order.expires_at)
    assert expired_draft.state == Order.State.EXPIRED

    another_order = Order.objects.create(
        buyer=buyer,
        vendor=order.vendor,
        listing=order.listing,
        listing_title=order.listing_title,
        quantity=1,
        unit_price=order.unit_price,
        total_amount=order.total_amount,
    )
    fund_test_order(buyer, another_order)
    funded = Order.objects.get(pk=another_order.pk)
    expired_funded = expire_funding(
        another_order.pk,
        now=funded.funded_at + timedelta(hours=12),
    )
    assert expired_funded.state == Order.State.REFUNDED
    assert get_ledger_account(Account.Kind.USER_ESCROW, owner=buyer).balance == 0


@pytest.mark.django_db
def test_buyer_cancels_only_draft_orders(participants) -> None:
    buyer, _, _, _, _, _, _, order = participants

    assert cancel_order(order.pk, buyer).state == Order.State.CANCELLED
    with pytest.raises(ValidationError, match="Illegal order transition"):
        cancel_order(order.pk, buyer)


@pytest.mark.django_db
def test_finalize_posts_distribution_and_buyer_can_extend_twice(participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    order.state = Order.State.DELIVERED
    order.delivered_at = timezone.now()
    order.finalize_at = timezone.now() + timedelta(hours=1)
    order.save(update_fields=("state", "delivered_at", "finalize_at"))

    initial_deadline = order.finalize_at
    extended = extend_finalize(order.pk, buyer)
    assert extended.finalize_at == initial_deadline + timedelta(hours=24)
    extended = extend_finalize(order.pk, buyer)
    assert extended.finalize_at == initial_deadline + timedelta(hours=48)
    with pytest.raises(ValidationError, match="extended twice"):
        extend_finalize(order.pk, buyer)

    settled = finalize(order.pk, now=extended.finalize_at)
    assert settled.state == Order.State.FINALIZED
    assert settled.released_amount == order.total_amount
    assert (
        get_ledger_account(
            Account.Kind.VENDOR_AVAILABLE,
            owner=order.vendor.user,
        ).balance
        == order.total_amount * 95 // 100
    )
    assert (
        get_ledger_account(Account.Kind.MARKET_FEE).balance
        == order.total_amount * 4 // 100
    )
    assert (
        get_ledger_account(Account.Kind.TREASURY).balance == order.total_amount // 100
    )
    assert get_ledger_account(Account.Kind.USER_ESCROW, owner=buyer).balance == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("outcome", "expected_state"),
    [
        (PublicRuling.Outcome.RELEASE, Order.State.FINALIZED),
        (PublicRuling.Outcome.REFUND, Order.State.REFUNDED),
        (PublicRuling.Outcome.PARTIAL, Order.State.PARTIAL),
    ],
)
def test_dispute_rulings_settle_escrow(
    participants,
    outcome: str,
    expected_state: str,
) -> None:
    buyer, _, _, _, _, category, _, order = participants
    fund_test_order(buyer, order)
    order.state = Order.State.DISPUTED
    order.save(update_fields=("state",))
    dispute = Dispute.objects.create(order=order, filed_by=buyer, reason="Review.")
    admin = User.objects.create_superuser(
        username=f"ruling_{outcome}",
        password="test-password",
    )

    rule_dispute(
        dispute.pk,
        admin,
        "100-200 base",
        category,
        outcome,
        reason="The order evidence supports this outcome.",
        released_amount_base_units=60_000_000
        if outcome == PublicRuling.Outcome.PARTIAL
        else None,
    )

    order.refresh_from_db()
    assert order.state == expected_state
    assert get_ledger_account(Account.Kind.USER_ESCROW, owner=buyer).balance == 0
    if outcome == PublicRuling.Outcome.PARTIAL:
        assert order.released_amount == 60_000_000
        assert (
            get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer).balance
            == 40_000_000
        )
        assert (
            get_ledger_account(
                Account.Kind.VENDOR_AVAILABLE,
                owner=order.vendor.user,
            ).balance
            == 57_000_000
        )
    elif outcome == PublicRuling.Outcome.REFUND:
        assert (
            get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer).balance
            == order.total_amount
        )
    else:
        assert (
            get_ledger_account(
                Account.Kind.VENDOR_AVAILABLE,
                owner=order.vendor.user,
            ).balance
            == order.total_amount * 95 // 100
        )


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_fund_requests_post_one_transfer(participants) -> None:
    if connections["default"].vendor != "postgresql":
        pytest.skip("select_for_update concurrency requires PostgreSQL.")
    buyer, _, _, _, _, _, _, order = participants
    external, _ = Account.objects.get_or_create(kind=Account.Kind.EXTERNAL, owner=None)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer)
    post_transfer(
        external,
        available,
        order.total_amount,
        f"test-concurrent-fund-{order.pk}",
        allow_external_source=True,
    )
    barrier = Barrier(2)

    def fund() -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=buyer.pk)
            barrier.wait(timeout=10)
            return fund_order(order.pk, actor).state
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: fund(), range(2))) == [
            Order.State.FUNDED,
            Order.State.FUNDED,
        ]
    assert LedgerEntry.objects.filter(ref=f"order-fund-{order.pk}").count() == 2


@pytest.mark.django_db(transaction=True)
def test_funding_racing_buyer_cancel_has_exactly_one_winner(participants) -> None:
    if connections["default"].vendor != "postgresql":
        pytest.skip("select_for_update concurrency requires PostgreSQL.")
    buyer, _, _, _, _, _, _, order = participants
    external, _ = Account.objects.get_or_create(kind=Account.Kind.EXTERNAL, owner=None)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer)
    post_transfer(
        external,
        available,
        order.total_amount,
        f"test-fund-cancel-{order.pk}",
        allow_external_source=True,
    )
    barrier = Barrier(2)

    def run(action: str) -> str:
        close_old_connections()
        try:
            actor = User.objects.get(pk=buyer.pk)
            barrier.wait(timeout=10)
            service = fund_order if action == "fund" else cancel_order
            try:
                return service(order.pk, actor).state
            except ValidationError:
                return "lost"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, ("fund", "cancel")))
    assert results.count("lost") == 1
    assert (
        sum(state in {Order.State.FUNDED, Order.State.CANCELLED} for state in results)
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_finalizations_lock_crossed_account_owners_in_order(
    participants,
) -> None:
    if connections["default"].vendor != "postgresql":
        pytest.skip("select_for_update concurrency requires PostgreSQL.")
    buyer, vendor_user, _, _, _, category, listing, first_order = participants
    reverse_vendor = create_vendor_profile(buyer)
    reverse_listing = Listing.objects.create(
        vendor=reverse_vendor,
        category=category,
        title="Reverse cup",
        description="A cup.",
        price=listing.price,
        stock=1,
        is_active=True,
    )
    second_order = Order.objects.create(
        buyer=vendor_user,
        vendor=reverse_vendor,
        listing=reverse_listing,
        listing_title=reverse_listing.title,
        quantity=1,
        unit_price=reverse_listing.price,
        total_amount=reverse_listing.price,
    )
    fund_test_order(buyer, first_order)
    fund_test_order(vendor_user, second_order)
    due = timezone.now() - timedelta(seconds=1)
    for order in (first_order, second_order):
        order.refresh_from_db()
        order.state = Order.State.DELIVERED
        order.finalize_at = due
        order.save(update_fields=("state", "finalize_at"))

    barrier = Barrier(2)

    def finish(order_id: int) -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return finalize(order_id, now=due).state
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(finish, (first_order.pk, second_order.pk)))

    assert outcomes == [Order.State.FINALIZED, Order.State.FINALIZED]


@pytest.mark.django_db
def test_pack_photo_is_validated_and_saved_with_random_filename(participants):
    _, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.ACCEPTED
    order.save(update_fields=("state",))

    packed = pack_order(order.pk, vendor_user, image_upload())

    assert packed.state == Order.State.PACKED
    assert packed.pack_photo.name.startswith("orders/private/pack/")
    assert packed.pack_photo.name.endswith(".png")
    assert "customer-name" not in packed.pack_photo.name
    assert packed.pack_photo.storage.exists(packed.pack_photo.name)


@pytest.mark.django_db
def test_pack_order_is_limited_to_vendor_and_accepted_state(participants):
    buyer, _, _, _, _, _, _, order = participants

    with pytest.raises(PermissionDenied):
        pack_order(order.pk, buyer, image_upload())

    with pytest.raises(ValidationError, match="Illegal order transition"):
        pack_order(order.pk, order.vendor.user, image_upload())

    order.refresh_from_db()
    assert order.state == Order.State.DRAFT


@pytest.mark.django_db
def test_dispatch_requires_pack_photo(participants):
    _, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.PACKED
    order.save(update_fields=("state",))

    with pytest.raises(ValidationError, match="pack photo"):
        dispatch_order(order.pk, vendor_user, "courier-123")

    order.refresh_from_db()
    assert order.state == Order.State.PACKED


@pytest.mark.django_db
def test_dispatch_stores_only_hashed_pod_token_with_six_hour_expiry(participants):
    _, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.PACKED
    order.pack_photo = "orders/pack/test.jpg"
    order.save(update_fields=("state", "pack_photo"))

    dispatched, token = dispatch_order(order.pk, vendor_user, "courier-123")

    assert dispatched.state == Order.State.DISPATCHED
    assert dispatched.courier_reference == "courier-123"
    assert dispatched.pod_token_hash != token
    assert len(dispatched.pod_token_hash) == 64
    assert dispatched.pod_token_expires_at - timezone.now() <= POD_TOKEN_LIFETIME
    assert (
        dispatched.pod_token_expires_at - timezone.now()
        > POD_TOKEN_LIFETIME - timedelta(seconds=2)
    )


@pytest.mark.django_db
def test_delivery_requires_valid_unexpired_token_and_consumes_it(participants):
    _, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.PACKED
    order.pack_photo = "orders/pack/test.jpg"
    order.save(update_fields=("state", "pack_photo"))
    _, token = dispatch_order(order.pk, vendor_user, "courier-456")

    delivered = record_delivery(order.pk, token)

    assert delivered.state == Order.State.DELIVERED
    assert delivered.delivered_at is not None
    assert delivered.pod_token_hash == ""
    assert delivered.pod_token_expires_at is None
    with pytest.raises(ValidationError, match="Illegal order transition"):
        record_delivery(order.pk, token)


@pytest.mark.django_db
def test_expired_pod_token_cannot_confirm_delivery(participants):
    _, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.PACKED
    order.pack_photo = "orders/pack/test.jpg"
    order.save(update_fields=("state", "pack_photo"))
    _, token = dispatch_order(order.pk, vendor_user, "courier-789")
    Order.objects.filter(pk=order.pk).update(
        pod_token_expires_at=timezone.now() - timedelta(seconds=1)
    )

    with pytest.raises(ValidationError, match="expired"):
        record_delivery(order.pk, token)

    order.refresh_from_db()
    assert order.state == Order.State.DISPATCHED


@pytest.mark.django_db
def test_contact_fields_are_encrypted_in_database_and_decrypted_on_read(participants):
    *_, order = participants
    table = Order._meta.db_table

    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT shipping_address, shipping_phone FROM "{table}" WHERE id = %s',
            [order.pk],
        )
        stored_address, stored_phone = cursor.fetchone()

    assert "12 Market Street" not in stored_address
    assert "+254700000000" not in stored_phone
    fetched = Order.objects.get(pk=order.pk)
    assert fetched.shipping_address == "12 Market Street"
    assert fetched.shipping_phone == "+254700000000"


@pytest.mark.django_db
def test_contact_field_requires_encryption_key(participants, settings):
    *_, order = participants
    settings.FIELD_ENCRYPTION_KEY = ""

    with pytest.raises(ImproperlyConfigured, match="FIELD_ENCRYPTION_KEY"):
        Order.objects.get(pk=order.pk)


@pytest.mark.django_db
def test_open_dispute_saves_private_attachment_and_updates_order(participants):
    buyer, _, _, _, _, _, _, order = participants
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(days=1)
    order.save(update_fields=("state", "finalize_at"))

    dispute = open_dispute(
        order.pk,
        buyer,
        "Package arrived damaged.",
        Dispute.EvidenceKind.BUYER_PAYMENT,
        evidence_upload(),
        "Receipt scan",
    )

    order.refresh_from_db()
    evidence = dispute.evidence.get()
    assert order.state == Order.State.DISPUTED
    assert order.dispute_at is not None
    assert evidence.attachment.name.startswith("orders/private/evidence/")
    assert evidence.attachment.storage.exists(evidence.attachment.name)
    assert "private-evidence" not in evidence.attachment.name


@pytest.mark.django_db
def test_only_order_participants_can_submit_dispute_evidence(participants):
    buyer, _, _, _, _, _, _, order = participants
    outsider = User.objects.create_user(username="outsider", password="unused")
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(days=1)
    order.save(update_fields=("state", "finalize_at"))
    dispute = open_dispute(
        order.pk,
        buyer,
        "Item did not arrive.",
        Dispute.EvidenceKind.DELIVERY,
        evidence_upload(),
    )

    with pytest.raises(PermissionDenied):
        submit_dispute_evidence(
            dispute.pk,
            outsider,
            Dispute.EvidenceKind.OTHER,
            evidence_upload("outsider.pdf"),
        )


@pytest.mark.django_db
def test_admin_ruling_is_public_without_party_names(participants, client):
    buyer, vendor_user, _, _, _, category, _, order = participants
    fund_test_order(buyer, order)
    order.state = Order.State.DISPUTED
    order.save(update_fields=("state",))
    dispute = Dispute.objects.create(
        order=order,
        filed_by=buyer,
        reason="Private dispute details.",
    )
    admin = User.objects.create_superuser(
        username="orders_admin",
        password="a-very-long-unique-password-8492",
    )

    with pytest.raises(PermissionDenied):
        rule_dispute(
            dispute.pk,
            buyer,
            "100-200 base",
            category,
            PublicRuling.Outcome.REFUND,
            reason="The evidence supports a refund.",
        )

    client.force_login(admin)
    response = client.post(
        reverse("orders:review-dispute", args=[dispute.pk]),
        {
            "amount_band": "100-200 base",
            "category": category.pk,
            "outcome": PublicRuling.Outcome.REFUND,
            "reason": "The submitted evidence supports a refund.",
        },
    )

    assert response.status_code == 302
    ruling = PublicRuling.objects.get(dispute=dispute)
    public = client.get(reverse("orders:public-ruling", args=[ruling.pk]))
    assert public.status_code == 200
    assert b"100-200 base" in public.content
    assert b"Refund buyer" in public.content
    assert buyer.username.encode() not in public.content
    assert vendor_user.username.encode() not in public.content
    assert b"Private dispute details" not in public.content


@pytest.mark.django_db
def test_public_ruling_cannot_be_edited_or_deleted(participants):
    buyer, _, _, _, _, category, _, order = participants
    fund_test_order(buyer, order)
    order.state = Order.State.DISPUTED
    order.save(update_fields=("state",))
    dispute = Dispute.objects.create(
        order=order,
        filed_by=buyer,
        reason="Private reason.",
    )
    admin = User.objects.create_superuser(
        username="ruling_admin",
        password="a-very-long-unique-password-8492",
    )
    ruling = rule_dispute(
        dispute.pk,
        admin,
        "100-200 base",
        category,
        PublicRuling.Outcome.PARTIAL,
        reason="The evidence supports a split release.",
        released_amount_base_units=order.total_amount // 2,
    )

    with pytest.raises(ValidationError, match="immutable"):
        ruling.save()
    with pytest.raises(ValidationError, match="immutable"):
        ruling.delete()


@pytest.mark.django_db
def test_ruling_rejects_non_amount_bands_and_unrelated_categories(participants):
    buyer, _, _, _, _, category, _, order = participants
    order.state = Order.State.DISPUTED
    order.save(update_fields=("state",))
    dispute = Dispute.objects.create(
        order=order, filed_by=buyer, reason="Private reason."
    )
    admin = User.objects.create_superuser(
        username="validation_admin",
        password="TestOnly-Validation-Password-123",
    )

    with pytest.raises(ValidationError, match="amount band"):
        rule_dispute(
            dispute.pk,
            admin,
            "buyer Alice",
            category,
            PublicRuling.Outcome.REFUND,
            reason="The evidence supports this ruling.",
        )

    unrelated_category = Category.objects.create(name="Other", slug="other")
    with pytest.raises(ValidationError, match="category"):
        rule_dispute(
            dispute.pk,
            admin,
            "100-200 base",
            unrelated_category,
            PublicRuling.Outcome.REFUND,
            reason="The evidence supports this ruling.",
        )

    assert not PublicRuling.objects.filter(dispute=dispute).exists()


@pytest.mark.django_db
def test_admin_review_and_evidence_download_are_staff_only(participants, client):
    buyer, _, _, _, _, _, _, order = participants
    order.state = Order.State.DISPUTED
    order.save(update_fields=("state",))
    dispute = Dispute.objects.create(order=order, filed_by=buyer, reason="Review this.")
    evidence = DisputeEvidence.objects.create(
        dispute=dispute,
        submitted_by=buyer,
        kind=Dispute.EvidenceKind.OTHER,
        attachment=evidence_upload(),
    )

    queue_url = reverse("orders:dispute-queue")
    download_url = reverse("orders:evidence-download", args=[evidence.pk])
    assert client.get(queue_url).status_code == 302
    assert client.get(download_url).status_code == 302

    admin = User.objects.create_superuser(
        username="review_admin",
        password="a-very-long-unique-password-8492",
    )
    client.force_login(admin)
    assert client.get(queue_url).status_code == 200
    download = client.get(download_url)
    assert download.status_code == 200
    assert download["Content-Disposition"].startswith("attachment;")


# ---------------------------------------------------------------------------
# New view tests — fund, cancel, accept, reject, extend_finalize
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fund_view_happy_path(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    # Seed ledger balance so fund_order succeeds.
    external, _ = Account.objects.get_or_create(kind=Account.Kind.EXTERNAL, owner=None)
    Account.objects.get_or_create(kind=Account.Kind.MARKET_FEE, owner=None)
    Account.objects.get_or_create(kind=Account.Kind.TREASURY, owner=None)
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer)
    post_transfer(
        external,
        available,
        order.total_amount,
        f"test-fund-view-{order.pk}",
        allow_external_source=True,
    )

    client.force_login(buyer)
    response = client.post(reverse("orders:fund", args=[order.pk]))

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.FUNDED


@pytest.mark.django_db
def test_fund_view_as_non_buyer_returns_403(client, participants) -> None:
    _, vendor_user, _, _, _, _, _, order = participants
    client.force_login(vendor_user)

    response = client.post(reverse("orders:fund", args=[order.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_cancel_view_happy_path(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    client.force_login(buyer)

    response = client.post(reverse("orders:cancel", args=[order.pk]))

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.CANCELLED


@pytest.mark.django_db
def test_cancel_view_on_funded_returns_400(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    client.force_login(buyer)

    response = client.post(reverse("orders:cancel", args=[order.pk]))

    assert response.status_code == 400


@pytest.mark.django_db
def test_accept_view_happy_path(client, participants) -> None:
    buyer, vendor_user, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    client.force_login(vendor_user)

    response = client.post(reverse("orders:accept", args=[order.pk]))

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.ACCEPTED


@pytest.mark.django_db
def test_accept_view_as_buyer_returns_403(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    client.force_login(buyer)

    response = client.post(reverse("orders:accept", args=[order.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_reject_view_happy_path(client, participants) -> None:
    buyer, vendor_user, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    client.force_login(vendor_user)

    response = client.post(reverse("orders:reject", args=[order.pk]))

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.REFUNDED


@pytest.mark.django_db
def test_reject_view_as_buyer_returns_403(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    client.force_login(buyer)

    response = client.post(reverse("orders:reject", args=[order.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_extend_finalize_view_happy_path(client, participants) -> None:
    from datetime import timedelta

    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    order.refresh_from_db()
    order.state = Order.State.DELIVERED
    order.delivered_at = timezone.now()
    order.finalize_at = timezone.now() + timedelta(hours=24)
    order.save(update_fields=("state", "delivered_at", "finalize_at"))
    original_deadline = order.finalize_at
    client.force_login(buyer)

    response = client.post(reverse("orders:extend-finalize", args=[order.pk]))

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.buyer_extensions == 1
    assert order.finalize_at > original_deadline


@pytest.mark.django_db
def test_extend_finalize_view_as_vendor_returns_403(client, participants) -> None:
    from datetime import timedelta

    buyer, vendor_user, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    order.refresh_from_db()
    order.state = Order.State.DELIVERED
    order.delivered_at = timezone.now()
    order.finalize_at = timezone.now() + timedelta(hours=24)
    order.save(update_fields=("state", "delivered_at", "finalize_at"))
    client.force_login(vendor_user)

    response = client.post(reverse("orders:extend-finalize", args=[order.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_extend_finalize_view_on_non_delivered_returns_400(
    client, participants
) -> None:
    buyer, _, _, _, _, _, _, order = participants
    # Order remains in DRAFT state.
    client.force_login(buyer)

    response = client.post(reverse("orders:extend-finalize", args=[order.pk]))

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Scheduler management command tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_run_scheduler_expires_draft_orders_past_deadline(participants) -> None:
    _, _, _, _, _, _, _, order = participants
    # Push expires_at into the past.
    Order.objects.filter(pk=order.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    call_command("run_scheduler")

    order.refresh_from_db()
    assert order.state == Order.State.EXPIRED


@pytest.mark.django_db
def test_run_scheduler_finalizes_delivered_orders(participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    order.refresh_from_db()
    order.state = Order.State.DELIVERED
    order.delivered_at = timezone.now() - timedelta(hours=25)
    order.finalize_at = timezone.now() - timedelta(minutes=1)
    order.save(update_fields=("state", "delivered_at", "finalize_at"))

    call_command("run_scheduler")

    order.refresh_from_db()
    assert order.state == Order.State.FINALIZED


@pytest.mark.django_db
def test_fund_view_illegal_state_returns_400(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    # Cancel the draft order first
    cancel_order(order.pk, buyer)
    client.force_login(buyer)

    response = client.post(reverse("orders:fund", args=[order.pk]))

    assert response.status_code == 400


@pytest.mark.django_db
def test_cancel_view_as_non_buyer_returns_403(client, participants) -> None:
    _, vendor_user, _, _, _, _, _, order = participants
    client.force_login(vendor_user)

    response = client.post(reverse("orders:cancel", args=[order.pk]))

    assert response.status_code == 403


@pytest.mark.django_db
def test_accept_view_illegal_state_returns_400(client, participants) -> None:
    _, vendor_user, _, _, _, _, _, order = participants
    # Order is still DRAFT (not FUNDED)
    client.force_login(vendor_user)

    response = client.post(reverse("orders:accept", args=[order.pk]))

    assert response.status_code == 400


@pytest.mark.django_db
def test_reject_view_illegal_state_returns_400(client, participants) -> None:
    _, vendor_user, _, _, _, _, _, order = participants
    # Order is still DRAFT (not FUNDED)
    client.force_login(vendor_user)

    response = client.post(reverse("orders:reject", args=[order.pk]))

    assert response.status_code == 400


@pytest.mark.django_db
def test_extend_finalize_view_after_two_extensions_returns_400(
    client, participants
) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    order.refresh_from_db()
    order.state = Order.State.DELIVERED
    order.delivered_at = timezone.now()
    order.finalize_at = timezone.now() + timedelta(hours=24)
    order.buyer_extensions = 2
    order.save(
        update_fields=("state", "delivered_at", "finalize_at", "buyer_extensions")
    )
    client.force_login(buyer)

    response = client.post(reverse("orders:extend-finalize", args=[order.pk]))

    assert response.status_code == 400


@pytest.mark.django_db
def test_open_dispute_view_happy_path(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(days=1)
    order.save(update_fields=("state", "finalize_at"))
    client.force_login(buyer)

    response = client.post(
        reverse("orders:open-dispute", args=[order.pk]),
        {
            "reason": "Damaged goods arrived.",
            "evidence_kind": Dispute.EvidenceKind.BUYER_PAYMENT,
            "description": "Proof of payment",
            "attachment": evidence_upload(),
        },
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.DISPUTED
    assert hasattr(order, "dispute")


@pytest.mark.django_db
def test_open_dispute_view_as_vendor_returns_403(client, participants) -> None:
    _, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(days=1)
    order.save(update_fields=("state", "finalize_at"))
    client.force_login(vendor_user)

    response = client.post(
        reverse("orders:open-dispute", args=[order.pk]),
        {
            "reason": "Vendor cannot open dispute.",
            "evidence_kind": Dispute.EvidenceKind.VENDOR_STATEMENT,
            "attachment": evidence_upload(),
        },
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_open_dispute_view_on_draft_returns_400(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    # Order is in DRAFT state
    client.force_login(buyer)

    response = client.post(
        reverse("orders:open-dispute", args=[order.pk]),
        {
            "reason": "Cannot dispute draft.",
            "evidence_kind": Dispute.EvidenceKind.BUYER_PAYMENT,
            "attachment": evidence_upload(),
        },
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_submit_dispute_evidence_view_happy_path(client, participants) -> None:
    buyer, vendor_user, _, _, _, _, _, order = participants
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(days=1)
    order.save(update_fields=("state", "finalize_at"))
    dispute = open_dispute(
        order.pk,
        buyer,
        "Package issue",
        Dispute.EvidenceKind.BUYER_PAYMENT,
        evidence_upload(),
    )
    client.force_login(vendor_user)

    response = client.post(
        reverse("orders:submit-evidence", args=[dispute.pk]),
        {
            "kind": Dispute.EvidenceKind.VENDOR_STATEMENT,
            "description": "Vendor counter-evidence",
            "attachment": evidence_upload("vendor.pdf"),
        },
    )

    assert response.status_code == 302
    assert dispute.evidence.filter(submitted_by=vendor_user).exists()


@pytest.mark.django_db
def test_submit_dispute_evidence_view_as_outsider_returns_403(
    client, participants
) -> None:
    buyer, _, _, _, _, _, _, order = participants
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(days=1)
    order.save(update_fields=("state", "finalize_at"))
    dispute = open_dispute(
        order.pk,
        buyer,
        "Package issue",
        Dispute.EvidenceKind.BUYER_PAYMENT,
        evidence_upload(),
    )
    outsider = User.objects.create_user(username="random_user", password="pwd")
    client.force_login(outsider)

    response = client.post(
        reverse("orders:submit-evidence", args=[dispute.pk]),
        {
            "kind": Dispute.EvidenceKind.OTHER,
            "attachment": evidence_upload("outsider.pdf"),
        },
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_pack_order_view_as_buyer_returns_403(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    order.state = Order.State.ACCEPTED
    order.save(update_fields=("state",))
    client.force_login(buyer)

    response = client.post(
        reverse("orders:pack", args=[order.pk]),
        {"photo": image_upload()},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_dispatch_order_view_as_buyer_returns_403(client, participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    order.state = Order.State.PACKED
    order.save(update_fields=("state",))
    client.force_login(buyer)

    response = client.post(
        reverse("orders:dispatch", args=[order.pk]),
        {"courier_reference": "ref-123"},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_run_scheduler_posts_nothing_on_second_run(participants) -> None:
    buyer, _, _, _, _, _, _, order = participants
    fund_test_order(buyer, order)
    order.refresh_from_db()
    order.state = Order.State.DELIVERED
    order.delivered_at = timezone.now() - timedelta(hours=25)
    order.finalize_at = timezone.now() - timedelta(minutes=1)
    order.save(update_fields=("state", "delivered_at", "finalize_at"))

    # First run finalizes and posts ledger entries
    call_command("run_scheduler")
    order.refresh_from_db()
    assert order.state == Order.State.FINALIZED

    entries_after_first = LedgerEntry.objects.count()
    assert entries_after_first > 0

    # Second run immediately after — must post nothing to the ledger
    call_command("run_scheduler")
    entries_after_second = LedgerEntry.objects.count()
    assert entries_after_second == entries_after_first


@pytest.mark.django_db
def test_order_detail_template_reads_transition_table(client, participants) -> None:
    buyer, vendor_user, _, _, _, _, _, order = participants
    client.force_login(buyer)

    # In DRAFT state, buyer should see fund and cancel forms
    response = client.get(reverse("orders:detail", args=[order.pk]))
    assert response.status_code == 200
    assert reverse("orders:fund", args=[order.pk]).encode() in response.content
    assert reverse("orders:cancel", args=[order.pk]).encode() in response.content
    assert reverse("orders:accept", args=[order.pk]).encode() not in response.content
    assert reverse("orders:reject", args=[order.pk]).encode() not in response.content

    # In FUNDED state, vendor should see accept and reject forms, buyer sees neither
    fund_test_order(buyer, order)
    order.refresh_from_db()
    client.force_login(vendor_user)
    response = client.get(reverse("orders:detail", args=[order.pk]))
    assert response.status_code == 200
    assert reverse("orders:accept", args=[order.pk]).encode() in response.content
    assert reverse("orders:reject", args=[order.pk]).encode() in response.content
    assert reverse("orders:fund", args=[order.pk]).encode() not in response.content
    assert reverse("orders:cancel", args=[order.pk]).encode() not in response.content


def _create_pagination_disputes(
    participants,
    count: int,
    *,
    with_rulings: bool = True,
) -> list[Dispute]:
    buyer, _, vendor, _, _, category, listing, existing_order = participants
    existing_order.state = Order.State.DISPUTED
    existing_order.save(update_fields=("state",))
    disputes = [
        Dispute.objects.create(
            order=existing_order,
            filed_by=buyer,
            reason="Pagination dispute 0.",
        )
    ]
    orders = Order.objects.bulk_create(
        [
            Order(
                buyer=buyer,
                vendor=vendor,
                listing=listing,
                listing_title=listing.title,
                quantity=1,
                unit_price=listing.price,
                total_amount=listing.price,
                state=Order.State.DISPUTED,
            )
            for _ in range(count - 1)
        ]
    )
    new_disputes = Dispute.objects.bulk_create(
        [
            Dispute(
                order=order,
                filed_by=buyer,
                reason="Pagination dispute.",
            )
            for order in orders
        ]
    )
    disputes.extend(new_disputes)
    if with_rulings:
        PublicRuling.objects.bulk_create(
            [
                PublicRuling(
                    dispute=dispute,
                    amount_band="small",
                    category=category,
                    outcome=PublicRuling.Outcome.REFUND,
                )
                for dispute in disputes
            ]
        )
    return disputes


@pytest.mark.django_db
def test_public_rulings_are_paginated(client, participants) -> None:
    _create_pagination_disputes(participants, 30)

    first_page = client.get(reverse("orders:public-rulings"))
    second_page = client.get(reverse("orders:public-rulings"), {"page": 2})

    assert len(first_page.context["rulings"]) == 25
    assert b"Next" in first_page.content
    assert len(second_page.context["rulings"]) == 5
    assert b"Previous" in second_page.content


@pytest.mark.django_db
def test_dispute_queue_is_paginated(client, participants) -> None:
    _create_pagination_disputes(participants, 30, with_rulings=False)
    admin = User.objects.create_superuser(username="dispute_pagination_admin")
    client.force_login(admin)

    first_page = client.get(reverse("orders:dispute-queue"))
    second_page = client.get(reverse("orders:dispute-queue"), {"page": 2})

    assert len(first_page.context["disputes"]) == 25
    assert b"Next" in first_page.content
    assert len(second_page.context["disputes"]) == 5
    assert b"Previous" in second_page.content


@pytest.mark.django_db
def test_funded_order_requires_vendor_in_database(participants) -> None:
    buyer, _, _, _, _, _, listing, _ = participants

    with pytest.raises(IntegrityError):
        Order.objects.create(
            buyer=buyer,
            vendor=None,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=listing.price,
            total_amount=listing.price,
            state=Order.State.FUNDED,
        )


@pytest.mark.django_db
def test_vendorless_order_detail_hides_vendor_actions(client, participants) -> None:
    buyer, _, _, _, _, _, listing, _ = participants
    order = Order(
        buyer=buyer,
        vendor=None,
        listing=listing,
        listing_title=listing.title,
        quantity=1,
        unit_price=listing.price,
        total_amount=listing.price,
        state=Order.State.DRAFT,
    )
    request = RequestFactory().get("/")
    request.user = buyer

    rendered = render_to_string(
        "orders/detail.html",
        {
            "order": order,
            "allowed_actions": {"pack", "accept", "reject", "dispatch"},
            "pod_token": None,
            "evidence_choices": Dispute.EvidenceKind.choices,
            "request": request,
            "market_role": "customer",
            "market_initials": "OB",
        },
        request=request,
    )

    assert "Pack order" not in rendered
    assert "Accept order" not in rendered
    assert "Reject order" not in rendered
    assert "Dispatch order" not in rendered


@pytest.mark.django_db
def test_order_history_includes_buyer_and_vendor_roles(client, participants) -> None:
    buyer, _vendor_user, vendor, _, _, _, listing, _ = participants
    buyer_vendor_profile = create_vendor_profile(buyer)
    other_buyer = User.objects.create_user(username="history_other_buyer")
    for index in range(2):
        Order.objects.create(
            buyer=buyer,
            vendor=vendor,
            listing=listing,
            listing_title=listing.title,
            quantity=1,
            unit_price=listing.price,
            total_amount=listing.price,
        )
        Order.objects.create(
            buyer=other_buyer,
            vendor=buyer_vendor_profile,
            listing=listing,
            listing_title=f"Product {index}",
            quantity=1,
            unit_price=listing.price,
            total_amount=listing.price,
        )
    client.force_login(buyer)

    response = client.get(reverse("orders:history"))

    assert response.status_code == 200
    assert len(response.context["orders"]) == 5
    assert response.content.count(b"Buyer") == 3
    assert response.content.count(b"Vendor") == 2
