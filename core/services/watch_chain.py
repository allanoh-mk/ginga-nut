from __future__ import annotations

from typing import TYPE_CHECKING

from core.services.capture_rate_feed import capture_rate_feed
from core.services.poll_deposits import poll_deposits
from payments.models import Chain

if TYPE_CHECKING:
    from payments.models import Deposit


def watch_chain(chain: str) -> list[Deposit]:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    capture_rate_feed(chain)
    return poll_deposits(chain)
