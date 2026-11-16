import re
from collections.abc import Iterable
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from payments.models import Chain, DepositAddress
from payments.providers.base import ChainProvider, ChainTransfer, ProviderError

_AMOUNT_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


def _to_atomic(value: object, decimals: int) -> int:
    text = str(value).strip()
    if not _AMOUNT_PATTERN.fullmatch(text):
        raise ProviderError("BTCPay returned an invalid amount.")
    whole, _, fraction = text.partition(".")
    if len(fraction) > decimals:
        raise ProviderError("BTCPay amount exceeds supported precision.")
    return int(whole) * (10**decimals) + int((fraction + ("0" * decimals))[:decimals])


class BTCPayProvider(ChainProvider):
    """BTCPay adapter entry point for BTC and LTC.

    BTCPay does not expose a provider-independent permanent-address API. The
    concrete Greenfield implementation is intentionally isolated here so it
    can be configured per deployment without exposing its credentials to views.
    """

    supports_deposit = True
    supports_withdrawal = False
    supports_balance = True

    def __init__(self, chain: str) -> None:
        if chain not in {Chain.BTC, Chain.LTC}:
            raise ValueError(f"Unsupported BTCPay chain: {chain}")
        if (
            not settings.BTCPAY_SERVER_URL
            or not settings.BTCPAY_STORE_ID
            or not settings.BTCPAY_API_KEY
        ):
            raise ImproperlyConfigured(
                "BTCPAY_SERVER_URL, BTCPAY_STORE_ID, and BTCPAY_API_KEY are required."
            )
        self.chain = chain
        self.decimals = 8
        self.base_url = settings.BTCPAY_SERVER_URL.rstrip("/")
        self.store_id = settings.BTCPAY_STORE_ID
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "Authorization": f"token {settings.BTCPAY_API_KEY}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=settings.RATE_FEED_TIMEOUT_SECONDS,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            raise ProviderError("BTCPay Greenfield request failed.") from error

    def _payment_method(self, methods: list[dict]) -> dict:
        expected = f"{self.chain}-CHAIN"
        for item in methods:
            method_id = str(item.get("paymentMethodId", "")).upper()
            if method_id == expected:
                return item
        raise ProviderError(f"BTCPay has no enabled on-chain method for {self.chain}.")

    def new_address(self, user, chain: str) -> tuple[str, str]:
        if chain != self.chain:
            raise ValueError("Provider chain does not match the requested chain.")
        invoice = self._request(
            "POST",
            f"/api/v1/stores/{self.store_id}/invoices",
            json={"amount": None, "currency": "USD"},
        )
        invoice_id = invoice.get("id")
        if not invoice_id:
            raise ProviderError("BTCPay did not return an invoice identifier.")
        methods = self._request(
            "GET",
            f"/api/v1/invoices/{invoice_id}/payment-methods",
            params={"includeSensitive": "true"},
        )
        destination = self._payment_method(methods).get("destination")
        if not destination:
            raise ProviderError("BTCPay invoice did not return a payment destination.")
        return destination, str(invoice_id)

    def poll(self) -> Iterable[ChainTransfer]:
        for address in DepositAddress.objects.filter(chain=self.chain).iterator():
            if not address.provider_reference:
                raise ProviderError("BTCPay deposit address is missing its invoice ID.")
            methods = self._request(
                "GET",
                f"/api/v1/invoices/{address.provider_reference}/payment-methods",
                params={
                    "includeSensitive": "true",
                    "onlyAccountedPayments": "false",
                },
            )
            method = self._payment_method(methods)
            for payment in method.get("payments", []):
                payment_id = payment.get("id")
                if not payment_id:
                    continue
                if payment.get("destination") not in {None, address.address}:
                    continue
                status = str(payment.get("status", "")).lower()
                confirmations = (
                    settings.MARKET_CHAIN_CONFIRMATIONS[self.chain]
                    if status == "settled"
                    else 0
                )
                yield ChainTransfer(
                    transaction_id=str(payment_id),
                    address=address.address,
                    amount_atomic=_to_atomic(payment.get("value", "0"), self.decimals),
                    confirmations=confirmations,
                )

    def wallet_balance(self) -> int:
        payment_method = f"{self.chain}-CHAIN"
        wallet = self._request(
            "GET",
            f"/api/v1/stores/{self.store_id}/payment-methods/{payment_method}/wallet",
        )
        if not isinstance(wallet, dict):
            raise ProviderError("BTCPay returned an invalid wallet description.")
        derivation_scheme = wallet.get("derivationScheme")
        if not derivation_scheme:
            raise ProviderError("BTCPay wallet has no derivation scheme.")
        balance = self._request(
            "GET",
            f"/api/v1/stores/{self.store_id}/payment-methods/{payment_method}"
            f"/wallet/{quote(derivation_scheme, safe='')}/balance",
        )
        if not isinstance(balance, dict) or not {
            "confirmed",
            "unconfirmed",
        }.issubset(balance):
            raise ProviderError("BTCPay returned an incomplete wallet balance.")
        confirmed = _to_atomic(balance["confirmed"], self.decimals)
        unconfirmed = _to_atomic(balance["unconfirmed"], self.decimals)
        return confirmed + unconfirmed

    def credit_amount(self, transfer) -> int:
        amount = transfer.amount_atomic
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ProviderError("BTCPay returned an invalid payment amount.")
        return amount
