import base64
import logging
from decimal import Decimal
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Listing
from core.services.create_vendor_profile import create_vendor_profile
from core.services.reserve_integrity import reserve_integrity
from core.services.reserve_report import reserve_report
from core.services.set_market_feature import set_market_feature
from ledger.models import Account, LedgerEntry
from ops.models import MarketSwitch, ReserveIntegrityRun, ReserveSnapshot
from orders.models import City, DeliveryZone, Dispute, Order
from payments.models import Chain, Deposit, DepositAddress, RateTick
from payments.providers.base import BalanceAdapterUnavailable
from payments.providers.fake import FakeProvider


@pytest.fixture(autouse=True)
def clear_fake_wallet_balances():
    FakeProvider._wallet_balances_atomic.clear()
    yield
    FakeProvider._wallet_balances_atomic.clear()


def _seed_balance(kind: str, amount: int, reference: str) -> Account:
    account = Account.objects.create(kind=kind)
    counter_account = Account.objects.create(kind=Account.Kind.TREASURY)
    LedgerEntry.objects.create(account=account, amount=amount, ref=reference)
    LedgerEntry.objects.create(account=counter_account, amount=-amount, ref=reference)
    return account


@pytest.mark.django_db
def test_reserve_report_sums_positive_liability_balances_not_revenue(settings):
    _seed_balance(Account.Kind.USER_AVAILABLE, 120, "buyer-funds")
    _seed_balance(Account.Kind.USER_ESCROW, 35, "order-escrow")
    _seed_balance(Account.Kind.VENDOR_AVAILABLE, 80, "vendor-payout")
    _seed_balance(Account.Kind.VENDOR_BOND, 12, "vendor-bond")
    _seed_balance(Account.Kind.SUSPENSE, 3, "unmatched-credit")
    _seed_balance(Account.Kind.MARKET_FEE, 700, "market-income")
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 200
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 125

    snapshot = reserve_report()

    assert snapshot.liability_base_units == 250
    assert snapshot.hot_balance_base_units == 200
    assert snapshot.cold_balance_base_units == 125
    assert snapshot.reserve_total_base_units == 325
    assert snapshot.ratio == Decimal("1.3")
    assert snapshot.below_warning_threshold is False


@pytest.mark.django_db
def test_reserve_report_ignores_negative_account_balances(settings):
    _seed_balance(Account.Kind.USER_AVAILABLE, 100, "positive-liability")
    _seed_balance(Account.Kind.USER_ESCROW, -900, "negative-liability")
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 0
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 0

    snapshot = reserve_report()

    assert snapshot.liability_base_units == 100


@pytest.mark.django_db
def test_reserve_report_logs_warning_below_1_3(settings, caplog):
    _seed_balance(Account.Kind.USER_AVAILABLE, 100, "low-coverage")
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 99
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 30

    with caplog.at_level(logging.WARNING, logger="core.services.reserve_report"):
        snapshot = reserve_report()

    assert snapshot.below_warning_threshold
    assert "is below 1.3:1." in caplog.text
    assert "1.2900:1" in caplog.text


@pytest.mark.django_db
def test_reserve_report_does_not_warn_without_liability(settings, caplog):
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 20
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 10

    with caplog.at_level(logging.WARNING, logger="core.services.reserve_report"):
        snapshot = reserve_report()

    assert snapshot.liability_base_units == 0
    assert snapshot.ratio is None
    assert not caplog.records


@pytest.mark.django_db
def test_reserve_report_rejects_invalid_configured_balances(settings):
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = -1
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 0

    with pytest.raises(ImproperlyConfigured, match="non-negative integer"):
        reserve_report()

    assert not ReserveSnapshot.objects.exists()


@pytest.mark.django_db
def test_command_creates_snapshot_and_prints_ratio(settings, capsys):
    _seed_balance(Account.Kind.USER_AVAILABLE, 200, "command-liability")
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 200
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 100

    call_command("reserve_report")

    assert ReserveSnapshot.objects.count() == 1
    assert "ratio=1.5000:1" in capsys.readouterr().out


@pytest.mark.django_db
def test_short_pending_deposit_trips_withdrawal_freeze() -> None:
    user = User.objects.create_user(username="reserve-pending")
    address = DepositAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address="pending-btc-address",
    )
    for txid, amount, state in (
        ("seen-deposit", 20, Deposit.State.SEEN),
        ("confirming-deposit", 30, Deposit.State.CONFIRMING),
        ("confirmed-deposit", 50, Deposit.State.CONFIRMED),
    ):
        Deposit.objects.create(
            address=address,
            transaction_id=txid,
            amount_atomic=amount,
            state=state,
        )
    FakeProvider(Chain.BTC).set_wallet_balance(98)

    run = reserve_integrity()

    assert run.results[Chain.BTC]["expected_units"] == 100
    assert run.results[Chain.BTC]["wallet_balance_units"] == 98
    assert run.results[Chain.BTC]["status"] == "shortfall"
    assert run.shortfall_chains == [Chain.BTC]
    assert MarketSwitch.objects.get().withdrawals_enabled is False


@pytest.mark.django_db
def test_one_percent_shortfall_does_not_trip_freeze() -> None:
    user = User.objects.create_user(username="reserve-at-threshold")
    address = DepositAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address="threshold-btc-address",
    )
    Deposit.objects.create(
        address=address,
        transaction_id="threshold-deposit",
        amount_atomic=100,
        state=Deposit.State.SEEN,
    )
    FakeProvider(Chain.BTC).set_wallet_balance(99)

    run = reserve_integrity()

    assert run.results[Chain.BTC]["shortfall_percent"] == "1.0000"
    assert run.results[Chain.BTC]["status"] == "measured"
    assert run.shortfall_chains == []
    assert MarketSwitch.objects.filter().first() is None


@pytest.mark.django_db
def test_converted_deposit_is_excluded_from_chain_liability() -> None:
    user = User.objects.create_user(username="reserve-converted")
    address = DepositAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address="converted-btc-address",
    )
    Deposit.objects.create(
        address=address,
        transaction_id="converted-deposit",
        amount_atomic=100,
        state=Deposit.State.CREDITED,
        conversion_processed_at=timezone.now(),
    )

    run = reserve_integrity()

    assert run.results[Chain.BTC]["expected_units"] == 0
    assert run.results[Chain.BTC]["status"] == "no_liability"
    assert Chain.BTC not in run.shortfall_chains


@pytest.mark.django_db
def test_missing_balance_adapter_is_unmeasurable_not_zero() -> None:
    class NoBalanceFake(FakeProvider):
        def wallet_balance(self) -> int:
            raise BalanceAdapterUnavailable("No test adapter.")

    user = User.objects.create_user(username="reserve-no-adapter")
    address = DepositAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address="no-adapter-btc-address",
    )
    Deposit.objects.create(
        address=address,
        transaction_id="no-adapter-deposit",
        amount_atomic=100,
        state=Deposit.State.CONFIRMING,
    )
    providers = {
        chain: (NoBalanceFake(chain) if chain == Chain.BTC else FakeProvider(chain))
        for chain in Chain.values
    }
    with patch(
        "core.services.reserve_integrity.get_chain_provider",
        side_effect=lambda chain: providers[chain],
    ):
        run = reserve_integrity()

    assert run.results[Chain.BTC]["status"] == "unmeasurable"
    assert run.results[Chain.BTC]["reason"] == "balance_adapter_missing"
    assert run.results[Chain.BTC]["expected_units"] == 100
    assert run.results[Chain.BTC]["wallet_balance_units"] is None
    assert {"chain": Chain.BTC, "reason": "balance_adapter_missing"} in (
        run.unmeasurable_chains
    )


@pytest.mark.django_db
def test_public_reserve_page_explains_missing_balance_adapter() -> None:
    class NoBalanceFake(FakeProvider):
        def wallet_balance(self) -> int:
            raise BalanceAdapterUnavailable("No test adapter.")

    providers = {
        chain: (NoBalanceFake(chain) if chain == Chain.BTC else FakeProvider(chain))
        for chain in Chain.values
    }
    with patch(
        "core.services.reserve_integrity.get_chain_provider",
        side_effect=lambda chain: providers[chain],
    ):
        reserve_integrity()

    response = Client().get(reverse("ops:reserves"))

    assert response.status_code == 200
    assert b"BTC" in response.content
    assert b"Unmeasurable" in response.content
    assert b"Balance adapter is missing" in response.content


@pytest.mark.django_db
def test_xmr_integrity_compares_base_liability_with_reserve_and_hot() -> None:
    _seed_balance(Account.Kind.USER_AVAILABLE, 100_000_000, "xmr-ledger-liability")
    now = timezone.now()
    for source in ("coinbase", "kraken"):
        RateTick.objects.create(
            chain=Chain.XMR,
            source=source,
            base_units_per_coin=100_000_000,
            observed_at=now,
        )
    FakeProvider(Chain.XMR).set_wallet_balance(10**12)

    run = reserve_integrity()

    assert run.results[Chain.XMR]["unit"] == "base"
    assert run.results[Chain.XMR]["expected_units"] == 100_000_000
    assert run.results[Chain.XMR]["wallet_balance_units"] == 100_000_000
    assert run.results[Chain.XMR]["coverage_ratio"] == "1.000000"


@pytest.mark.django_db
def test_public_reserve_page_shows_integrity_ratio_and_fake_balance() -> None:
    user = User.objects.create_user(username="reserve-public")
    address = DepositAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address="public-btc-address",
    )
    Deposit.objects.create(
        address=address,
        transaction_id="public-pending-deposit",
        amount_atomic=150,
        state=Deposit.State.CONFIRMING,
    )
    FakeProvider(Chain.BTC).set_wallet_balance(150)
    run = reserve_integrity()

    response = Client().get(reverse("ops:reserves"))

    assert response.status_code == 200
    assert b"Per-chain reserve integrity" in response.content
    assert b"Last run" in response.content
    assert b"BTC" in response.content
    assert b"1.00:1" in response.content
    assert b"150" in response.content
    assert b"Unmeasurable" in response.content
    assert run.pk == ReserveIntegrityRun.objects.first().pk


@pytest.mark.django_db
def test_public_reserve_page_shows_latest_snapshot_and_history():
    first = ReserveSnapshot.objects.create(
        liability_base_units=250,
        hot_balance_base_units=250,
        cold_balance_base_units=0,
    )
    ReserveSnapshot.objects.create(
        liability_base_units=250,
        hot_balance_base_units=300,
        cold_balance_base_units=200,
    )

    response = Client().get(reverse("ops:reserves"))

    assert response.status_code == 200
    assert b"Coverage ratio" in response.content
    assert b"2.00" in response.content
    assert str(first.liability_base_units).encode() in response.content
    assert b"Snapshot history" in response.content
    assert b"2 reports" in response.content


@pytest.mark.django_db
def test_site_stylesheet_is_served_in_production_mode(settings, client):
    settings.DEBUG = False

    response = client.get("/static/css/site.css")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/css")
    assert "max-age=0" in response["Cache-Control"]
    assert b".role-avatar--vendor" in b"".join(response.streaming_content)


@pytest.mark.django_db
def test_reserve_snapshots_are_immutable():
    snapshot = ReserveSnapshot.objects.create(
        liability_base_units=10,
        hot_balance_base_units=8,
        cold_balance_base_units=5,
    )

    with pytest.raises(ValidationError, match="immutable"):
        snapshot.save()
    with pytest.raises(ValidationError, match="immutable"):
        snapshot.delete()
    with pytest.raises(ValidationError, match="immutable"):
        ReserveSnapshot.objects.filter(pk=snapshot.pk).update(liability_base_units=1)
    with pytest.raises(ValidationError, match="immutable"):
        ReserveSnapshot.objects.filter(pk=snapshot.pk).delete()


@pytest.mark.django_db
def test_kill_switch_commands_pause_and_restore_orders() -> None:
    call_command("kill_new_orders")
    switch = MarketSwitch.objects.get()
    assert not switch.new_orders_enabled
    with pytest.raises(ValidationError, match="temporarily paused"):
        Order.objects.create()
    with pytest.raises(ValidationError, match="temporarily paused"):
        Order.objects.bulk_create([Order()])

    call_command("kill_new_orders", "--enable")
    switch.refresh_from_db()
    assert switch.new_orders_enabled


@pytest.mark.django_db
def test_kill_switch_command_pauses_and_restores_withdrawals() -> None:
    call_command("kill_withdrawals")
    switch = MarketSwitch.objects.get()
    assert not switch.withdrawals_enabled

    call_command("kill_withdrawals", "--enable")
    switch.refresh_from_db()
    assert switch.withdrawals_enabled


@pytest.mark.django_db
def test_ops_dashboard_shows_liabilities_disputes_queue_and_city_counts(
    settings,
) -> None:
    admin = User.objects.create_user(
        username="ops-admin",
        password="a-strong-password",
        is_staff=True,
    )
    vendor_user = User.objects.create_user(username="ops-dashboard-vendor")
    vendor = create_vendor_profile(vendor_user)
    category = Category.objects.create(name="Dashboard", slug="dashboard")
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="Dashboard item",
        description="Dashboard item.",
        price=100,
        stock=1,
        is_active=True,
    )
    city = City.objects.create(name="Nairobi", slug="nairobi")
    zone = DeliveryZone.objects.create(city=city, name="Central")
    order = Order.objects.create(
        buyer=admin,
        vendor=vendor,
        listing=listing,
        listing_title=listing.title,
        state=Order.State.DISPUTED,
        delivery_zone=zone,
        quantity=1,
        unit_price=listing.price,
        total_amount=100,
    )
    Dispute.objects.create(order=order, filed_by=admin, reason="Review needed.")
    _seed_balance(Account.Kind.USER_AVAILABLE, 100, "dashboard-liability")
    settings.RESERVE_HOT_BALANCE_BASE_UNITS = 100
    settings.RESERVE_COLD_BALANCE_BASE_UNITS = 50
    set_market_feature("new_orders", False)

    with patch(
        "core.services.get_ops_dashboard_metrics.Redis.from_url"
    ) as redis_from_url:
        redis_from_url.return_value.zcard.return_value = 2
        client = Client()
        client.force_login(admin)
        response = client.get(reverse("ops:dashboard"))

    assert response.status_code == 200
    assert response.context["liabilities"] == 100
    assert response.context["ratio"] == Decimal("1.5")
    assert response.context["open_disputes"] == 1
    assert response.context["queue_total"] == 2
    assert response.context["city_orders"] == [{"name": "Nairobi", "order_count": 1}]
    assert not response.context["new_orders_enabled"]
    assert b"Queue depth" in response.content


@pytest.mark.django_db
def test_ops_dashboard_marks_queue_depth_unavailable_on_redis_error() -> None:
    from redis.exceptions import RedisError

    admin = User.objects.create_user(
        username="queue-admin",
        is_staff=True,
    )
    client = Client()
    client.force_login(admin)
    with patch(
        "core.services.get_ops_dashboard_metrics.Redis.from_url"
    ) as redis_from_url:
        redis_from_url.return_value.ping.side_effect = RedisError("offline")
        response = client.get(reverse("ops:dashboard"))

    assert response.status_code == 200
    assert response.context["queue_depths"] is None
    assert b"Redis could not be reached" in response.content


@pytest.mark.django_db
def test_ops_dashboard_requires_staff_access() -> None:
    client = Client()
    response = client.get(reverse("ops:dashboard"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


@pytest.mark.django_db
def test_canary_page_exposes_verifiable_ed25519_statement(settings) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_seed = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    statement = "Market ledger reconciled at 2026-11-06T00:00:00Z."
    settings.CANARY_STATEMENT = statement
    settings.CANARY_SIGNING_KEY = base64.b64encode(private_seed).decode("ascii")

    response = Client().get(reverse("ops:canary"))

    assert response.status_code == 200
    signature = response.context["canary"]["signature"]
    public_key = response.context["canary"]["public_key"]
    Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key)).verify(
        base64.b64decode(signature), statement.encode("utf-8")
    )
    assert statement.encode() in response.content


@pytest.mark.django_db
def test_canary_page_explicitly_reports_unconfigured_signature(settings) -> None:
    settings.CANARY_STATEMENT = ""
    settings.CANARY_SIGNING_KEY = ""

    response = Client().get(reverse("ops:canary"))

    assert response.status_code == 200
    assert b"Canary statement is not configured" in response.content


@pytest.mark.django_db
def test_health_endpoint_checks_database_and_redis() -> None:
    with patch("ops.views.Redis.from_url") as redis_from_url:
        redis_from_url.return_value.zcard.return_value = 3
        response = Client().get(reverse("ops:health"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["redis"]["financial_queue_depth"] == 3
    assert payload["postgres"]["connections"]["total_connections"] >= 1
    assert payload["postgres"]["connections"]["max_connections"] > 0
    assert payload["postgres"]["pool"]["available"] is False
    assert payload["scheduler"]["last_run_at"] is None
    assert payload["scheduler"]["available"] is False
    assert payload["deposit_poll"]["last_run_at"] is None
    assert payload["deposit_poll"]["available"] is False
    redis_from_url.return_value.ping.assert_called_once_with()
    redis_from_url.return_value.zcard.assert_called_once()


@pytest.mark.django_db
def test_health_endpoint_reports_redis_unavailable() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    with patch("ops.views.Redis.from_url") as redis_from_url:
        redis_from_url.return_value.ping.side_effect = RedisConnectionError()
        response = Client().get(reverse("ops:health"))

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["unhealthy"] == ["redis"]
    assert payload["redis"]["financial_queue_depth"] is None


@pytest.mark.django_db
def test_health_endpoint_remains_public_and_reports_database_failure() -> None:
    from django.db import DatabaseError

    with (
        patch("ops.views.connection.cursor", side_effect=DatabaseError()),
        patch("ops.views.Redis.from_url"),
    ):
        response = Client().get(reverse("ops:health"))

    assert response.status_code == 503
    payload = response.json()
    assert payload["unhealthy"] == ["database"]
    assert payload["postgres"]["connections"] is None
