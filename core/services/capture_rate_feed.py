from django.db import transaction

from payments.models import Chain, RateTick
from payments.providers.rates import RATE_SOURCE_NAMES, fetch_rate_samples


@transaction.atomic
def capture_rate_feed(chain: str) -> tuple[RateTick, RateTick]:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain rate pair: {chain}")
    samples = fetch_rate_samples(chain)
    if tuple(sample.source for sample in samples) != RATE_SOURCE_NAMES:
        raise ValueError("Rate providers returned unexpected source identities.")
    ticks = tuple(
        RateTick.objects.create(
            chain=chain,
            source=sample.source,
            base_units_per_coin=sample.base_units_per_coin,
            observed_at=sample.observed_at,
        )
        for sample in samples
    )
    return ticks[0], ticks[1]
