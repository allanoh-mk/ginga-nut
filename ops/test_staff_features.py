from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Listing
from core.services.create_vendor_profile import create_vendor_profile
from ledger.models import LedgerEntry
from ops.models import MarketSwitch, MarketSwitchChange
from orders.models import City, DeliveryZone, Dispute, Order, PublicRuling
from payments.models import Chain, Deposit, DepositAddress, Withdrawal


@pytest.fixture(autouse=True)
def temporary_order_encryption_key(settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture
def staff_market(db):
    staff = User.objects.create_user(username="ops-staff", is_staff=True)
    buyer = User.objects.create_user(username="market-buyer")
    vendor_user = User.objects.create_user(username="market-vendor")
    vendor = create_vendor_profile(vendor_user)
    vendor.is_approved = True
    vendor.save(update_fields=("is_approved",))
    category = Category.objects.create(name="Kitchen", slug="kitchen")
    city = City.objects.create(name="Nairobi", slug="nairobi")
    zone = DeliveryZone.objects.create(city=city, name="Central")
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="Ceramic cup",
        description="A cup",
        price=500,
        stock=10,
        is_active=True,
    )
    order = Order.objects.create(
        buyer=buyer,
        vendor=vendor,
        listing=listing,
        listing_title=listing.title,
        total_amount=500,
        delivery_zone=zone,
    )
    return {
        "staff": staff,
        "buyer": buyer,
        "vendor": vendor,
        "vendor_user": vendor_user,
        "category": category,
        "city": city,
        "listing": listing,
        "order": order,
    }


@pytest.mark.django_db
def test_staff_order_list_filters_and_participant_or_staff_can_view_order(
    client,
    staff_market,
):
    client.force_login(staff_market["staff"])
    response = client.get(
        reverse("ops:order-list"),
        {"status": Order.State.DRAFT, "city": staff_market["city"].pk},
    )

    assert response.status_code == 200
    assert b"Ceramic cup" in response.content
    assert response.context["page_obj"].paginator.per_page == 25
    assert (
        client.get(
            reverse("orders:detail", args=(staff_market["order"].pk,))
        ).status_code
        == 200
    )

    client.force_login(staff_market["buyer"])
    assert (
        client.get(
            reverse("orders:detail", args=(staff_market["order"].pk,))
        ).status_code
        == 200
    )
    assert client.get(reverse("ops:order-list")).status_code == 302


@pytest.mark.django_db
def test_staff_order_list_paginates_and_applies_date_range(client, staff_market):
    order = staff_market["order"]
    for _ in range(25):
        Order.objects.create(
            buyer=staff_market["buyer"],
            vendor=staff_market["vendor"],
            listing=staff_market["listing"],
            listing_title=staff_market["listing"].title,
            total_amount=500,
            delivery_zone=order.delivery_zone,
        )
    client.force_login(staff_market["staff"])
    today = timezone.localdate().isoformat()

    filtered = client.get(
        reverse("ops:order-list"),
        {
            "status": Order.State.DRAFT,
            "city": staff_market["city"].pk,
            "start_date": today,
            "end_date": today,
        },
    )
    second_page = client.get(reverse("ops:order-list"), {"page": 2})

    assert filtered.status_code == 200
    assert filtered.context["page_obj"].paginator.count == 26
    assert filtered.context["page_obj"].paginator.per_page == 25
    assert second_page.context["page_obj"].number == 2
    assert len(second_page.context["page_obj"]) == 1


@pytest.mark.django_db
def test_staff_order_detail_hides_participant_actions(client, staff_market):
    order = staff_market["order"]
    order.state = Order.State.FUNDED
    order.funded_at = timezone.now()
    order.save(update_fields=("state", "funded_at"))
    client.force_login(staff_market["staff"])

    response = client.get(reverse("orders:detail", args=(order.pk,)))

    assert response.status_code == 200
    assert b"Staff order controls" in response.content
    assert b"Record staff transition" in response.content
    assert b"/orders/" + str(order.pk).encode() + b"/accept/" not in response.content
    assert b"/orders/" + str(order.pk).encode() + b"/fund/" not in response.content


@pytest.mark.django_db
def test_force_transition_requires_reason_and_valid_next_state(
    client,
    staff_market,
):
    order = staff_market["order"]
    order.state = Order.State.FUNDED
    order.funded_at = timezone.now()
    order.save(update_fields=("state", "funded_at"))
    client.force_login(staff_market["staff"])
    url = reverse("ops:order-force-transition", args=(order.pk,))

    invalid = client.post(
        url,
        {"target_state": Order.State.REFUNDED, "reason": "Override"},
    )
    assert invalid.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.FUNDED
    assert not order.staff_transition_logs.exists()

    missing_reason = client.post(
        url,
        {"target_state": Order.State.ACCEPTED, "reason": "   "},
    )
    assert missing_reason.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.FUNDED

    changed = client.post(
        url,
        {"target_state": Order.State.ACCEPTED, "reason": "Vendor confirmed by phone"},
    )
    assert changed.status_code == 302
    order.refresh_from_db()
    audit = order.staff_transition_logs.get()
    assert order.state == Order.State.ACCEPTED
    assert (audit.from_state, audit.to_state) == (
        Order.State.FUNDED,
        Order.State.ACCEPTED,
    )
    assert audit.actor == staff_market["staff"]
    assert audit.reason == "Vendor confirmed by phone"
    assert audit.created_at is not None


@pytest.mark.django_db
def test_nonstaff_cannot_force_transition(client, staff_market):
    order = staff_market["order"]
    order.state = Order.State.FUNDED
    order.funded_at = timezone.now()
    order.save(update_fields=("state", "funded_at"))
    client.force_login(staff_market["buyer"])

    response = client.post(
        reverse("ops:order-force-transition", args=(order.pk,)),
        {"target_state": Order.State.ACCEPTED, "reason": "Not staff"},
    )

    assert response.status_code == 302
    order.refresh_from_db()
    assert order.state == Order.State.FUNDED
    assert not order.staff_transition_logs.exists()


@pytest.mark.django_db
def test_staff_can_deactivate_listing_and_it_disappears_from_public_catalog(
    client,
    staff_market,
):
    listing = staff_market["listing"]
    staff = staff_market["staff"]
    staff.is_superuser = True
    staff.save(update_fields=("is_superuser",))
    client.force_login(staff)
    change_url = reverse("admin:catalog_listing_change", args=(listing.pk,))
    form = client.get(change_url)

    assert form.status_code == 200
    assert b'name="is_active"' in form.content
    assert b'name="title"' not in form.content
    assert b'name="shipping_required"' not in form.content
    assert b'name="average_rating"' not in form.content

    response = client.post(change_url, {"is_active": ""})
    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.is_active is False

    public = client.get(reverse("catalog:search"))
    assert b"Ceramic cup" not in public.content
    assert client.get(reverse("catalog:listing", args=(listing.pk,))).status_code == 404


@pytest.mark.django_db
def test_staff_market_switch_post_requires_reason_and_records_change(
    client,
    staff_market,
):
    client.force_login(staff_market["staff"])
    url = reverse("ops:market-switch-toggle", args=("new_orders",))

    missing_reason = client.post(url, {"reason": "  "})
    assert missing_reason.status_code == 302
    assert MarketSwitchChange.objects.count() == 0

    changed = client.post(url, {"reason": "Pause for incident response"})

    assert changed.status_code == 302
    switch = MarketSwitch.objects.get()
    assert switch.new_orders_enabled is False
    assert MarketSwitchChange.objects.get().enabled is False
    assert MarketSwitchChange.objects.get().actor == staff_market["staff"]
    assert MarketSwitchChange.objects.get().reason == "Pause for incident response"
    client.post(url, {"reason": "Incident resolved"})
    switch.refresh_from_db()
    assert switch.new_orders_enabled is True
    assert MarketSwitchChange.objects.count() == 2


@pytest.mark.django_db
def test_nonstaff_cannot_toggle_market_switch(client, staff_market):
    client.force_login(staff_market["buyer"])

    response = client.post(
        reverse("ops:market-switch-toggle", args=("new_orders",)),
        {"reason": "Unauthorized"},
    )

    assert response.status_code == 302
    assert MarketSwitchChange.objects.count() == 0


@pytest.mark.django_db
def test_staff_override_rejects_financial_transition_without_ledger_effects(
    client,
    staff_market,
):
    order = staff_market["order"]
    order.state = Order.State.FUNDED
    order.funded_at = timezone.now()
    order.save(update_fields=("state", "funded_at"))
    client.force_login(staff_market["staff"])
    ledger_entries_before = LedgerEntry.objects.count()

    response = client.post(
        reverse("ops:order-force-transition", args=(order.pk,)),
        {"target_state": Order.State.REFUNDED, "reason": "Refund requested"},
        follow=True,
    )

    order.refresh_from_db()
    assert order.state == Order.State.FUNDED
    assert not order.staff_transition_logs.exists()
    assert LedgerEntry.objects.count() == ledger_entries_before
    assert b"financial and fulfillment side effects" in response.content


@pytest.mark.django_db
def test_operations_dashboard_aggregates_market_activity(staff_market, settings):
    from core.services.get_ops_dashboard_metrics import get_ops_dashboard_metrics

    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 0
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 0
    order = staff_market["order"]
    Order.objects.create(
        buyer=staff_market["buyer"],
        vendor=staff_market["vendor"],
        listing=staff_market["listing"],
        listing_title=staff_market["listing"].title,
        total_amount=700,
        state=Order.State.FINALIZED,
        delivery_zone=order.delivery_zone,
    )
    dispute = Dispute.objects.create(
        order=order,
        filed_by=staff_market["buyer"],
        reason="Item was damaged",
    )
    PublicRuling.objects.create(
        dispute=dispute,
        amount_band="1-1000",
        category=staff_market["category"],
        outcome=PublicRuling.Outcome.REFUND,
    )
    address = DepositAddress.objects.create(
        user=staff_market["buyer"],
        chain=Chain.BTC,
        address="dashboard-btc-address",
    )
    Deposit.objects.create(
        address=address,
        transaction_id="dashboard-deposit",
        amount_atomic=100,
        base_amount=900,
        state=Deposit.State.CREDITED,
        credited_at=timezone.now(),
        conversion_processed_at=timezone.now(),
    )
    Withdrawal.objects.create(
        user=staff_market["buyer"],
        chain=Chain.BTC,
        destination="dashboard-destination",
        amount_base_units=300,
        fee_base_units=10,
        idempotency_key="dashboard-withdrawal",
    )
    for index in range(12):
        Order.objects.create(
            buyer=staff_market["buyer"],
            vendor=staff_market["vendor"],
            listing=staff_market["listing"],
            listing_title=staff_market["listing"].title,
            total_amount=50 + index,
            delivery_zone=order.delivery_zone,
        )
    MarketSwitch.objects.get_or_create(pk=MarketSwitch.Key.GLOBAL)

    with (
        patch("core.services.get_ops_dashboard_metrics.Redis.from_url") as redis,
        CaptureQueriesContext(connection) as queries,
    ):
        redis.return_value.ping.return_value = True
        redis.return_value.zcard.return_value = 0
        metrics = get_ops_dashboard_metrics()

    assert len(queries) <= 20
    assert metrics["status_counts"][Order.State.DRAFT] == 13
    assert metrics["status_counts"][Order.State.FINALIZED] == 1
    assert metrics["finalized_gmv"] == 700
    assert metrics["dispute_outcomes"][PublicRuling.Outcome.REFUND] == 1
    assert metrics["deposits_30d"][Chain.BTC]["volume"] == 900
    assert metrics["withdrawals_30d"][Chain.BTC]["volume"] == 300
    assert metrics["top_vendors"][0]["order_count"] == 14
    assert metrics["top_listings"][0]["order_count"] == 14


@pytest.mark.django_db
def test_operations_dashboard_ranks_top_vendors_and_listings_by_order_count(
    staff_market,
    settings,
):
    from core.services.get_ops_dashboard_metrics import get_ops_dashboard_metrics

    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 0
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 0
    high_value_order = staff_market["order"]
    high_value_order.state = Order.State.FINALIZED
    high_value_order.total_amount = 100_000
    high_value_order.save(update_fields=("state", "total_amount"))

    second_vendor_user = User.objects.create_user(username="more-orders-vendor")
    second_vendor = create_vendor_profile(second_vendor_user)
    second_listing = Listing.objects.create(
        vendor=second_vendor,
        category=staff_market["category"],
        title="More orders listing",
        description="A lower-value listing",
        price=1,
        stock=10,
        is_active=True,
    )
    for _ in range(2):
        Order.objects.create(
            buyer=staff_market["buyer"],
            vendor=second_vendor,
            listing=second_listing,
            listing_title=second_listing.title,
            total_amount=1,
            state=Order.State.FINALIZED,
            delivery_zone=high_value_order.delivery_zone,
        )

    with patch("core.services.get_ops_dashboard_metrics.Redis.from_url") as redis:
        redis.return_value.ping.return_value = True
        redis.return_value.zcard.return_value = 0
        metrics = get_ops_dashboard_metrics()

    assert metrics["top_vendors"][0]["user__username"] == "more-orders-vendor"
    assert metrics["top_vendors"][0]["order_count"] == 2
    assert metrics["top_listings"][0]["title"] == "More orders listing"
    assert metrics["top_listings"][0]["order_count"] == 2
