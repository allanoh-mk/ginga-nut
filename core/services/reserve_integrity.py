import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.services.set_market_feature import set_market_feature
from ledger.models import Account
from ops.models import ReserveIntegrityRun
from payments.models import Chain, Deposit, MoneroOrderEscrow, RateTick
from payments.providers import get_chain_provider
from payments.providers.base import BalanceAdapterUnavailable, ProviderError
from payments.providers.rates import RATE_SOURCE_NAMES

logger = logging.getLogger(__name__)
_LIABILITY_KINDS = (
    Account.Kind.USER_AVAILABLE,
    Account.Kind.USER_ESCROW,
    Account.Kind.VENDOR_AVAILABLE,
    Account.Kind.VENDOR_BOND,
    Account.Kind.SUSPENSE,
)


def _ledger_liability() -> int:
    ledger_total = (
        Account.objects.filter(kind__in=_LIABILITY_KINDS)
        .annotate(account_balance=Sum("entries__amount"))
        .filter(account_balance__gt=0)
        .aggregate(total=Sum("account_balance"))["total"]
        or 0
    )
    multisig_total = (
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
    return ledger_total + multisig_total


def _xmr_rate() -> int | None:
    now = timezone.now()
    ticks = {
        source: RateTick.objects.filter(chain=Chain.XMR, source=source)
        .order_by("-observed_at", "-pk")
        .first()
        for source in RATE_SOURCE_NAMES
    }
    if any(tick is None for tick in ticks.values()):
        return None
    rates = [tick.base_units_per_coin for tick in ticks.values() if tick]
    if any(rate <= 0 for rate in rates):
        return None
    if any(
        (now - tick.observed_at).total_seconds() > settings.RATE_FEED_STALE_SECONDS
        for tick in ticks.values()
        if tick
    ):
        return None
    lower, upper = sorted(rates)
    if (upper - lower) * 100 > lower:
        return None
    return lower


def _non_xmr_liability(chain: str) -> int:
    return (
        Deposit.objects.filter(
            address__chain=chain,
            state__in=(
                Deposit.State.SEEN,
                Deposit.State.CONFIRMING,
                Deposit.State.CONFIRMED,
            ),
            conversion_processed_at__isnull=True,
        ).aggregate(total=Sum("amount_atomic"))["total"]
        or 0
    )


def _result(expected: int, balance: int, unit: str) -> dict:
    if expected == 0:
        return {
            "status": "no_liability",
            "unit": unit,
            "expected_units": 0,
            "wallet_balance_units": balance,
            "coverage_ratio": None,
            "shortfall_percent": None,
        }
    ratio = Decimal(balance) / Decimal(expected)
    shortfall = max(0, expected - balance)
    return {
        "status": "shortfall" if shortfall * 100 > expected else "measured",
        "unit": unit,
        "expected_units": expected,
        "wallet_balance_units": balance,
        "coverage_ratio": format(ratio, ".6f"),
        "shortfall_percent": format(
            Decimal(shortfall) * Decimal(100) / Decimal(expected),
            ".4f",
        ),
    }


def reserve_integrity() -> ReserveIntegrityRun:
    results: dict[str, dict] = {}
    shortfall_chains: list[str] = []
    unmeasurable_chains: list[dict[str, str]] = []

    for chain in Chain.values:
        provider = get_chain_provider(chain)
        expected = (
            _ledger_liability() if chain == Chain.XMR else _non_xmr_liability(chain)
        )
        try:
            wallet_balance = provider.wallet_balance()
        except BalanceAdapterUnavailable:
            results[chain] = {
                "status": "unmeasurable",
                "reason": "balance_adapter_missing",
                "expected_units": expected,
                "wallet_balance_units": None,
                "coverage_ratio": None,
                "shortfall_percent": None,
            }
            unmeasurable_chains.append(
                {"chain": chain, "reason": "balance_adapter_missing"}
            )
            continue
        if (
            isinstance(wallet_balance, bool)
            or not isinstance(wallet_balance, int)
            or wallet_balance < 0
        ):
            raise ProviderError(
                f"{chain} wallet balance adapter returned an invalid amount."
            )

        if chain == Chain.XMR:
            conversion_rate = _xmr_rate()
            if conversion_rate is None:
                results[chain] = {
                    "status": "unmeasurable",
                    "reason": "xmr_rate_unavailable",
                    "expected_units": expected,
                    "wallet_balance_units": None,
                    "coverage_ratio": None,
                    "shortfall_percent": None,
                }
                unmeasurable_chains.append(
                    {"chain": chain, "reason": "xmr_rate_unavailable"}
                )
                continue
            wallet_balance = wallet_balance * conversion_rate // (10**provider.decimals)
            unit = "base"
        else:
            unit = "atomic"

        chain_result = _result(expected, wallet_balance, unit)
        results[chain] = chain_result
        if chain_result["status"] == "shortfall":
            shortfall_chains.append(chain)

    with transaction.atomic():
        run = ReserveIntegrityRun.objects.create(
            results=results,
            shortfall_chains=shortfall_chains,
            unmeasurable_chains=unmeasurable_chains,
        )
        if shortfall_chains:
            set_market_feature("withdrawals", False)

    if shortfall_chains:
        logger.critical(
            "Reserve integrity shortfall exceeded one percent; withdrawals disabled.",
            extra={
                "reserve_integrity_run_id": run.pk,
                "shortfall_chains": shortfall_chains,
            },
        )
    if unmeasurable_chains:
        logger.warning(
            "Reserve integrity could not measure one or more chains.",
            extra={
                "reserve_integrity_run_id": run.pk,
                "unmeasurable_chains": unmeasurable_chains,
            },
        )
    return run
