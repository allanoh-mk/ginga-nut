import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q, Sum

from ledger.models import Account
from ops.models import ReserveSnapshot
from payments.models import MoneroOrderEscrow

logger = logging.getLogger(__name__)


def _configured_balance(setting_name: str) -> int:
    value = getattr(settings, setting_name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ImproperlyConfigured(
            f"{setting_name} must be a non-negative integer base-unit balance."
        )
    return value


def reserve_report() -> ReserveSnapshot:
    liability_kinds = (
        Account.Kind.USER_AVAILABLE,
        Account.Kind.USER_ESCROW,
        Account.Kind.VENDOR_AVAILABLE,
        Account.Kind.VENDOR_BOND,
        Account.Kind.SUSPENSE,
    )
    liability = (
        Account.objects.filter(kind__in=liability_kinds)
        .annotate(account_balance=Sum("entries__amount"))
        .filter(account_balance__gt=0)
        .aggregate(total=Sum("account_balance"))["total"]
        or 0
    )
    liability += (
        MoneroOrderEscrow.objects.filter(
            Q(
                state__in=(
                    MoneroOrderEscrow.State.FUNDED,
                    MoneroOrderEscrow.State.SETTLEMENT_PENDING,
                )
            )
            | Q(
                state=MoneroOrderEscrow.State.REVIEW,
                received_amount_atomic__gt=0,
            )
        ).aggregate(total=Sum("order__total_amount"))["total"]
        or 0
    )
    hot_balance = _configured_balance("RESERVE_HOT_BALANCE_BASE_UNITS")
    cold_balance = _configured_balance("RESERVE_COLD_BALANCE_BASE_UNITS")

    snapshot = ReserveSnapshot.objects.create(
        liability_base_units=liability,
        hot_balance_base_units=hot_balance,
        cold_balance_base_units=cold_balance,
    )
    if snapshot.below_warning_threshold:
        logger.warning(
            "Reserve ratio %s:1 is below 1.3:1.",
            f"{snapshot.ratio:.4f}",
            extra={
                "reserve_snapshot_id": snapshot.pk,
                "liability_base_units": liability,
                "hot_balance_base_units": hot_balance,
                "cold_balance_base_units": cold_balance,
                "reserve_ratio": str(snapshot.ratio),
            },
        )
    return snapshot
