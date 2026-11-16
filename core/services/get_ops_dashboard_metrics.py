from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from redis import Redis
from redis.exceptions import RedisError

from catalog.models import Listing, VendorProfile
from core.jobs import FINANCIAL_JOB_QUEUE
from ledger.models import Account
from ops.models import MarketSwitch
from orders.models import City, Dispute, Order, PublicRuling
from payments.models import Chain, Deposit, Withdrawal


def _configured_balance(setting_name: str) -> int:
    value = getattr(settings, setting_name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ImproperlyConfigured(
            f"{setting_name} must be a non-negative integer base-unit balance."
        )
    return value


def get_ops_dashboard_metrics() -> dict:
    liability_kinds = (
        Account.Kind.USER_AVAILABLE,
        Account.Kind.USER_ESCROW,
        Account.Kind.VENDOR_AVAILABLE,
        Account.Kind.VENDOR_BOND,
        Account.Kind.SUSPENSE,
    )
    liabilities = (
        Account.objects.filter(kind__in=liability_kinds)
        .annotate(account_balance=Sum("entries__amount"))
        .filter(account_balance__gt=0)
        .aggregate(total=Sum("account_balance"))["total"]
        or 0
    )
    hot = _configured_balance("RESERVE_HOT_BALANCE_BASE_UNITS")
    cold = _configured_balance("RESERVE_COLD_BALANCE_BASE_UNITS")
    ratio = Decimal(hot + cold) / Decimal(liabilities) if liabilities else None
    below_reserve_threshold = liabilities > 0 and (hot + cold) * 10 < liabilities * 13

    redis_client = Redis.from_url(settings.QUEUE_REDIS_URL, decode_responses=True)
    try:
        redis_client.ping()
        queue_depths = {
            "withdrawals": redis_client.zcard(FINANCIAL_JOB_QUEUE),
        }
    except RedisError:
        queue_depths = None
    finally:
        redis_client.close()

    switches, _ = MarketSwitch.objects.get_or_create(pk=MarketSwitch.Key.GLOBAL)
    city_orders = list(
        City.objects.annotate(order_count=Count("delivery_zones__orders"))
        .order_by("name")
        .values("name", "order_count")
    )
    unassigned_orders = Order.objects.filter(delivery_zone__isnull=True).count()
    if unassigned_orders:
        city_orders.append({"name": "Unassigned", "order_count": unassigned_orders})
    status_counts = {state: 0 for state, _label in Order.State.choices}
    status_counts.update(
        {
            row["state"]: row["count"]
            for row in Order.objects.values("state").annotate(count=Count("pk"))
        }
    )
    finalized_filter = Q(orders__state=Order.State.FINALIZED)
    top_vendors = list(
        VendorProfile.objects.select_related("user")
        .annotate(
            order_count=Count("orders"),
            finalized_gmv=Sum(
                "orders__total_amount",
                filter=finalized_filter,
                default=0,
            ),
        )
        .order_by("-order_count", "-finalized_gmv", "user__username")
        .values(
            "user__username",
            "order_count",
            "finalized_gmv",
        )[:10]
    )
    top_listings = list(
        Listing.objects.annotate(
            order_count=Count("orders"),
            finalized_gmv=Sum(
                "orders__total_amount",
                filter=finalized_filter,
                default=0,
            ),
        )
        .order_by("-order_count", "-finalized_gmv", "title")
        .values("title", "order_count", "finalized_gmv")[:10]
    )
    dispute_outcomes = {outcome: 0 for outcome, _label in PublicRuling.Outcome.choices}
    dispute_outcomes.update(
        {
            row["outcome"]: row["count"]
            for row in PublicRuling.objects.values("outcome").annotate(
                count=Count("pk")
            )
        }
    )
    dispute_counts = {
        "total": Dispute.objects.count(),
        "open": Dispute.objects.filter(
            order__state=Order.State.DISPUTED,
            public_ruling__isnull=True,
        ).count(),
        "ruled": PublicRuling.objects.count(),
        "outcomes": dispute_outcomes,
    }

    cutoff = timezone.now() - timedelta(days=30)
    deposits_30d = {chain: {"count": 0, "volume": 0} for chain, _label in Chain.choices}
    for row in (
        Deposit.objects.filter(credited_at__gte=cutoff)
        .values(chain=F("address__chain"))
        .annotate(count=Count("pk"), volume=Sum("base_amount"))
    ):
        deposits_30d[row["chain"]] = {
            "count": row["count"],
            "volume": row["volume"] or 0,
        }
    withdrawals_30d = {
        chain: {"count": 0, "volume": 0} for chain, _label in Chain.choices
    }
    for row in (
        Withdrawal.objects.filter(created_at__gte=cutoff)
        .values("chain")
        .annotate(count=Count("pk"), volume=Sum("amount_base_units"))
    ):
        withdrawals_30d[row["chain"]] = {
            "count": row["count"],
            "volume": row["volume"] or 0,
        }

    return {
        "liabilities": liabilities,
        "hot_reserves": hot,
        "cold_reserves": cold,
        "ratio": ratio,
        "below_reserve_threshold": below_reserve_threshold,
        "open_disputes": dispute_counts["open"],
        "status_counts": status_counts,
        "finalized_gmv": Order.objects.filter(state=Order.State.FINALIZED).aggregate(
            total=Sum("total_amount")
        )["total"]
        or 0,
        "top_vendors": top_vendors,
        "top_listings": top_listings,
        "dispute_counts": dispute_counts,
        "dispute_outcomes": dispute_outcomes,
        "deposits_30d": deposits_30d,
        "withdrawals_30d": withdrawals_30d,
        "queue_depths": queue_depths,
        "queue_total": sum(queue_depths.values()) if queue_depths is not None else None,
        "city_orders": city_orders,
        "withdrawals_enabled": switches.withdrawals_enabled,
        "new_orders_enabled": switches.new_orders_enabled,
    }
