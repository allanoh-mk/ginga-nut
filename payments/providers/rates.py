import re
from dataclasses import dataclass
from datetime import datetime

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from payments.models import Chain

RATE_SOURCE_NAMES = ("coinbase", "kraken")


@dataclass(frozen=True)
class RateSample:
    source: str
    base_units_per_coin: int
    observed_at: datetime


_FIXED_RATE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_COINBASE_SYMBOLS = {
    Chain.BTC: "BTC",
    Chain.LTC: "LTC",
    Chain.XMR: "XMR",
    Chain.TRC20: None,
}
_KRAKEN_SYMBOLS = {
    Chain.BTC: "XBT",
    Chain.LTC: "LTC",
    Chain.XMR: "XMR",
    Chain.TRC20: None,
}


def _rate_to_base_units(value: object) -> int:
    text = str(value).strip()
    if not _FIXED_RATE.fullmatch(text):
        raise ValueError("Rate feed returned an invalid fixed-point rate.")
    whole, _, fraction = text.partition(".")
    if len(fraction) > 8:
        raise ValueError("Rate feed precision exceeds eight decimal places.")
    return int(whole) * 100_000_000 + int((fraction + "00000000")[:8])


def fetch_rate_samples(chain: str) -> tuple[RateSample, RateSample]:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain rate pair: {chain}")
    coinbase_symbol = _COINBASE_SYMBOLS[chain]
    kraken_symbol = _KRAKEN_SYMBOLS[chain]
    if chain == Chain.TRC20:
        configured_symbol = settings.TRC20_RATE_SYMBOL.strip().upper()
        if not configured_symbol:
            raise ImproperlyConfigured("TRC20_RATE_SYMBOL must be configured.")
        coinbase_symbol = configured_symbol
        kraken_symbol = configured_symbol

    proxy = settings.RATE_FEED_SOCKS_PROXY
    if not proxy.startswith("socks5h://"):
        raise ImproperlyConfigured(
            "Rate feeds require a Tor SOCKS5 proxy using socks5h://."
        )
    proxies = {"http": proxy, "https": proxy}
    session = requests.Session()
    session.trust_env = False
    coinbase = session.get(
        f"https://api.coinbase.com/v2/prices/{coinbase_symbol}-USD/spot",
        proxies=proxies,
        timeout=settings.RATE_FEED_TIMEOUT_SECONDS,
    )
    coinbase.raise_for_status()
    coinbase_data = coinbase.json()["data"]
    coinbase_rate = _rate_to_base_units(coinbase_data["amount"])

    kraken = session.get(
        "https://api.kraken.com/0/public/Ticker",
        params={"pair": f"{kraken_symbol}USD"},
        proxies=proxies,
        timeout=settings.RATE_FEED_TIMEOUT_SECONDS,
    )
    kraken.raise_for_status()
    kraken_data = kraken.json()
    if kraken_data.get("error"):
        raise RuntimeError("Kraken rate feed returned an error.")
    result = kraken_data["result"]
    if len(result) != 1:
        raise RuntimeError("Kraken rate feed returned an ambiguous pair.")
    kraken_rate = _rate_to_base_units(next(iter(result.values()))["c"][0])
    observed_at = timezone.now()
    return (
        RateSample("coinbase", coinbase_rate, observed_at),
        RateSample("kraken", kraken_rate, observed_at),
    )
