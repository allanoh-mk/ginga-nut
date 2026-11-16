from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from payments.models import Chain, RateQuote, RateTick
from payments.providers.rates import RATE_SOURCE_NAMES


class RateDivergence(ValidationError):
    pass


@transaction.atomic
def issue_rate_quote(
    user,
    chain: str,
    amount_min_atomic: int,
    amount_max_atomic: int,
) -> RateQuote:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    if (
        isinstance(amount_min_atomic, bool)
        or isinstance(amount_max_atomic, bool)
        or not isinstance(amount_min_atomic, int)
        or not isinstance(amount_max_atomic, int)
        or amount_min_atomic <= 0
        or amount_max_atomic < amount_min_atomic
    ):
        raise ValueError("Quote amount band must be positive and ordered.")
    tick_a, tick_b, median, now = _fresh_rate_pair(chain)
    return RateQuote.objects.create(
        user=user,
        chain=chain,
        source_a=tick_a,
        source_b=tick_b,
        base_units_per_coin=median,
        amount_min_atomic=amount_min_atomic,
        amount_max_atomic=amount_max_atomic,
        locked_until=now + timedelta(seconds=settings.RATE_QUOTE_LOCK_SECONDS),
    )


@transaction.atomic
def issue_xmr_rate_quote_for_base_amount(
    user,
    chain: str,
    amount_base_units: int,
) -> RateQuote:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    if chain != Chain.XMR:
        raise ValueError("Base-amount quotes currently support XMR only.")
    if (
        isinstance(amount_base_units, bool)
        or not isinstance(amount_base_units, int)
        or amount_base_units <= 0
    ):
        raise ValueError("Quote base amount must be a positive integer.")
    tick_a, tick_b, median, now = _fresh_rate_pair(chain)
    amount_atomic = (amount_base_units * (10**12) + median - 1) // median
    if amount_atomic <= 0:
        raise ValidationError("Quote amount converts to less than one atomic unit.")
    return RateQuote.objects.create(
        user=user,
        chain=chain,
        source_a=tick_a,
        source_b=tick_b,
        base_units_per_coin=median,
        amount_min_atomic=amount_atomic,
        amount_max_atomic=amount_atomic,
        locked_until=now + timedelta(seconds=settings.RATE_QUOTE_LOCK_SECONDS),
    )


def _fresh_rate_pair(chain: str):
    now = timezone.now()
    ticks = {
        source: RateTick.objects.filter(chain=chain, source=source)
        .order_by("-observed_at", "-pk")
        .first()
        for source in RATE_SOURCE_NAMES
    }
    if any(tick is None for tick in ticks.values()):
        raise RateDivergence("Rate feed is stale; quotes are paused.")
    tick_a = ticks[RATE_SOURCE_NAMES[0]]
    tick_b = ticks[RATE_SOURCE_NAMES[1]]
    assert tick_a is not None and tick_b is not None
    for tick in (tick_a, tick_b):
        age_seconds = (now - tick.observed_at).total_seconds()
        if age_seconds > settings.RATE_FEED_STALE_SECONDS:
            raise RateDivergence("Rate feed is stale; quotes are paused.")
    lower, upper = sorted((tick_a.base_units_per_coin, tick_b.base_units_per_coin))
    median = (lower + upper) // 2
    if median <= 0 or (upper - lower) * 100 > median:
        raise RateDivergence("Rate sources diverge by more than one percent.")
    return tick_a, tick_b, median, now
