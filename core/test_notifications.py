from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Listing
from core.models import Notification
from core.services.create_vendor_profile import create_vendor_profile
from core.services.fund_order import fund_order
from core.services.get_ledger_account import get_ledger_account
from core.services.open_dispute import open_dispute
from core.services.order_transitions import apply_order_transition
from core.services.post_transfer import post_transfer
from ledger.models import Account
from orders.models import Dispute, Order


@pytest.fixture
def notification_order(db):
    buyer = User.objects.create_user(username="notify-buyer")
    vendor_user = User.objects.create_user(username="notify-vendor")
    vendor = create_vendor_profile(vendor_user)
    category = Category.objects.create(
        name="Notification items", slug="notification-items"
    )
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="Notification item",
        description="A notification test item.",
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
    )
    return buyer, vendor_user, order


@pytest.mark.django_db
def test_funding_notifies_vendor_and_dispute_notifies_buyer(notification_order):
    buyer, vendor_user, order = notification_order
    external, _ = Account.objects.get_or_create(
        kind=Account.Kind.EXTERNAL,
        owner=None,
    )
    available = get_ledger_account(Account.Kind.USER_AVAILABLE, owner=buyer)
    post_transfer(
        external,
        available,
        order.total_amount,
        f"notification-test-funding-{order.pk}",
        allow_external_source=True,
    )

    fund_order(order.pk, buyer)

    funded_notification = Notification.objects.get(
        recipient=vendor_user,
        type=Notification.Type.ORDER_FUNDED,
    )
    assert funded_notification.data == {"order_id": order.pk}

    order.refresh_from_db()
    order.state = Order.State.DELIVERED
    order.finalize_at = timezone.now() + timedelta(hours=1)
    order.save(update_fields=("state", "finalize_at", "updated_at"))
    attachment = SimpleUploadedFile(
        "evidence.pdf",
        b"%PDF-1.4 test evidence",
        content_type="application/pdf",
    )
    open_dispute(
        order.pk,
        buyer,
        "The item did not arrive.",
        Dispute.EvidenceKind.DELIVERY,
        attachment,
    )

    assert Notification.objects.filter(
        recipient=buyer,
        type=Notification.Type.DISPUTE_OPENED,
    ).exists()
    assert Notification.objects.filter(
        recipient=vendor_user,
        type=Notification.Type.DISPUTE_OPENED,
    ).exists()


@pytest.mark.django_db
def test_cancel_expiry_and_monero_pending_notify_relevant_parties(notification_order):
    buyer, vendor_user, order = notification_order

    apply_order_transition(order, "cancel", actor=buyer)
    assert Notification.objects.filter(
        recipient=vendor_user,
        type=Notification.Type.ORDER_CANCELLED,
    ).exists()

    order.state = Order.State.DRAFT
    apply_order_transition(order, "expire")
    assert Notification.objects.filter(
        recipient=buyer,
        type=Notification.Type.ORDER_EXPIRED,
    ).exists()

    order.state = Order.State.DRAFT
    apply_order_transition(order, "xmr_settlement_pending")
    assert Notification.objects.filter(
        recipient=buyer,
        type=Notification.Type.SETTLEMENT_PENDING,
    ).exists()
    assert Notification.objects.filter(
        recipient=vendor_user,
        type=Notification.Type.SETTLEMENT_PENDING,
    ).exists()


@pytest.mark.django_db
def test_notification_badge_open_marks_read_and_mark_all_read(
    client, notification_order
):
    buyer, _, order = notification_order
    first = Notification.objects.create(
        recipient=buyer,
        type=Notification.Type.ORDER_FUNDED,
        message="Order funded.",
        data={"order_id": order.pk},
    )
    Notification.objects.create(
        recipient=buyer,
        type=Notification.Type.ORDER_DELIVERED,
        message="Order delivered.",
        data={"order_id": order.pk},
    )
    client.force_login(buyer)

    header = client.get(reverse("catalog:categories"))
    assert b"2 unread" in header.content
    opened = client.get(
        reverse("core:open-notification", args=(first.pk,)),
    )
    assert opened.status_code == 302
    first.refresh_from_db()
    assert first.read_at is not None
    assert opened["Location"] == reverse("orders:detail", args=(order.pk,))

    marked = client.post(reverse("core:mark-all-read"))
    assert marked.status_code == 302
    assert (
        Notification.objects.filter(
            recipient=buyer,
            read_at__isnull=True,
        ).count()
        == 0
    )
    assert client.get(reverse("catalog:categories")).content.count(b"unread") == 0
