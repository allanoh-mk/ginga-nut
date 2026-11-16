from collections.abc import Iterable
from importlib import import_module
from time import sleep
from urllib.parse import parse_qs, urlparse

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from tronpy.keys import to_hex_address

from payments.models import Chain, ChainPollWatermark, DepositAddress
from payments.providers.base import ChainProvider, ChainTransfer, ProviderError


class TronGridProvider(ChainProvider):
    supports_deposit = True
    supports_withdrawal = False
    supports_balance = True
    watermark_provider = "trongrid"
    # Three retries means four total attempts; waits are between attempts.
    retry_waits = (1, 5, 25)

    def __init__(self) -> None:
        if not settings.TRONGRID_API_URL or not settings.TRC20_CONTRACT_WHITELIST:
            raise ImproperlyConfigured(
                "TRONGRID_API_URL and TRC20_CONTRACT_WHITELIST are required."
            )
        if not settings.TRON_ADDRESS_DERIVER:
            raise ImproperlyConfigured(
                "Configure a local TRON_ADDRESS_DERIVER for secure address creation."
            )
        self.chain = Chain.TRC20
        self.decimals = settings.TRC20_TOKEN_DECIMALS
        if self.decimals <= 0 or self.decimals > 18:
            raise ImproperlyConfigured(
                "TRC20_TOKEN_DECIMALS must be in the range 1-18."
            )
        self.base_url = settings.TRONGRID_API_URL.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        if settings.TRONGRID_API_KEY:
            self.session.headers["TRON-PRO-API-KEY"] = settings.TRONGRID_API_KEY

    def _request(self, method: str, path: str, **kwargs):
        for attempt in range(len(self.retry_waits) + 1):
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
                if attempt == len(self.retry_waits):
                    raise ProviderError("TronGrid request failed.") from error
                sleep(self.retry_waits[attempt])

    @staticmethod
    def _next_fingerprint(page: dict, item_count: int) -> str | None:
        """Read TronGrid's documented meta.fingerprint pagination cursor."""
        meta = page.get("meta")
        if not isinstance(meta, dict):
            if item_count >= 200:
                raise ProviderError("TronGrid omitted pagination metadata.")
            return None
        links = meta.get("links")
        next_link = links.get("next") if isinstance(links, dict) else None
        link_fingerprint = None
        if isinstance(next_link, str):
            link_fingerprint = parse_qs(urlparse(next_link).query).get(
                "fingerprint", [None]
            )[0]
        fingerprint = meta.get("fingerprint") or link_fingerprint
        if fingerprint:
            return str(fingerprint)
        if isinstance(links, dict) and not next_link:
            return None
        if next_link:
            raise ProviderError("TronGrid next-page link omitted its fingerprint.")
        if item_count >= 200:
            raise ProviderError("TronGrid omitted the cursor for a full page.")
        return None

    def _watermark(self) -> int:
        return (
            ChainPollWatermark.objects.filter(
                provider=self.watermark_provider,
                chain=self.chain,
            )
            .values_list("last_block", flat=True)
            .first()
            or 0
        )

    def commit_poll(self) -> None:
        """Advance only after the caller has recorded the complete scan."""
        if self._pending_watermark is None:
            return
        with transaction.atomic():
            watermark, _ = ChainPollWatermark.objects.select_for_update().get_or_create(
                provider=self.watermark_provider,
                chain=self.chain,
            )
            watermark.last_block = max(watermark.last_block, self._pending_watermark)
            watermark.save(update_fields=("last_block", "updated_at"))
        self._pending_watermark = None

    def _derive_address(self, user) -> tuple[str, str]:
        module_name, function_name = settings.TRON_ADDRESS_DERIVER.rsplit(":", 1)
        deriver = getattr(import_module(module_name), function_name)
        result = deriver(user)
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not result[0]
            or not result[1]
        ):
            raise ProviderError("TRON address deriver returned invalid data.")
        return str(result[0]), str(result[1])

    def _is_tether_blacklisted(self, address: str) -> bool:
        address_hex = to_hex_address(address)
        parameter = address_hex[-40:].rjust(64, "0")
        payload = self._request(
            "POST",
            "/wallet/triggerconstantcontract",
            json={
                "owner_address": address_hex,
                "contract_address": to_hex_address(settings.TETHER_TRC20_CONTRACT),
                "function_selector": "isBlackListed(address)",
                "parameter": parameter,
                "visible": False,
            },
        )
        if not isinstance(payload, dict):
            raise ProviderError("TronGrid returned an invalid blacklist response.")
        call_result = payload.get("result")
        if not isinstance(call_result, dict) or call_result.get("result") is not True:
            raise ProviderError("TronGrid could not read Tether blacklist status.")
        results = payload.get("constant_result")
        if (
            not isinstance(results, list)
            or not results
            or not isinstance(results[0], str)
        ):
            raise ProviderError("TronGrid returned no Tether blacklist result.")
        try:
            return int(results[0], 16) != 0
        except ValueError as error:
            raise ProviderError(
                "TronGrid returned an invalid blacklist result."
            ) from error

    def new_address(self, user, chain: str) -> tuple[str, str]:
        if chain != self.chain:
            raise ValueError("Provider chain does not match the requested chain.")
        return self._derive_address(user)

    def poll(self) -> Iterable[ChainTransfer]:
        self._pending_watermark = None
        current_block_payload = self._request("POST", "/wallet/getnowblock", json={})
        current_block = (
            current_block_payload.get("block", {})
            .get("block_header", {})
            .get("raw_data", {})
            .get("number")
        )
        if isinstance(current_block, bool) or not isinstance(current_block, int):
            raise ProviderError("TronGrid did not return a current block height.")
        # The account endpoint has no block-number filter, so validate its
        # transaction-info block numbers against this lower bound client-side.
        first_block = self._watermark() + 1
        for address in DepositAddress.objects.filter(chain=self.chain).iterator():
            for contract in settings.TRC20_CONTRACT_WHITELIST:
                yield from self.fetch_transfers(
                    address,
                    contract,
                    first_block,
                    current_block,
                )
        self._pending_watermark = current_block

    def fetch_transfers(
        self,
        address: DepositAddress,
        contract: str,
        start_block: int,
        end_block: int,
    ) -> Iterable[ChainTransfer]:
        fingerprint = None
        seen_fingerprints = set()
        while True:
            params = {
                "only_confirmed": "false",
                "limit": 200,
                "contract_address": contract,
                "order_by": "block_timestamp,desc",
            }
            if fingerprint:
                params["fingerprint"] = fingerprint
            page = self._request(
                "GET",
                f"/v1/accounts/{address.address}/transactions/trc20",
                params=params,
            )
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ProviderError("TronGrid returned an invalid transfer page.")
            for item in page["data"]:
                if not isinstance(item, dict):
                    raise ProviderError("TronGrid returned invalid transfer data.")
                transfer = self._transfer_from_item(
                    item,
                    address,
                    contract,
                    end_block,
                    start_block,
                )
                if transfer is not None:
                    yield transfer
            next_fingerprint = self._next_fingerprint(page, len(page["data"]))
            if next_fingerprint is None:
                return
            if next_fingerprint in seen_fingerprints:
                raise ProviderError("TronGrid repeated a pagination cursor.")
            seen_fingerprints.add(next_fingerprint)
            fingerprint = next_fingerprint

    def _transfer_from_item(
        self,
        item: dict,
        address: DepositAddress,
        contract: str,
        current_block: int,
        first_block: int,
    ) -> ChainTransfer | None:
        token = item.get("token_info", {})
        contract_address = str(token.get("address", "")).lower()
        if contract_address != contract.lower():
            return None
        if token.get("decimals") != self.decimals:
            raise ProviderError("TRC-20 token decimals do not match configuration.")
        if (
            str(token.get("symbol", "")).upper()
            != settings.TRC20_RATE_SYMBOL.strip().upper()
        ):
            raise ProviderError(
                "TRC-20 token symbol does not match the configured rate pair."
            )
        transaction_id = item.get("transaction_id") or item.get("txID")
        amount_value = item.get("value")
        sender = item.get("from")
        destination = item.get("to")
        if (
            not transaction_id
            or not sender
            or not destination
            or isinstance(amount_value, bool)
        ):
            raise ProviderError("TronGrid returned invalid transfer data.")
        try:
            amount = int(amount_value)
        except (TypeError, ValueError) as error:
            raise ProviderError(
                "TronGrid returned a non-integer token amount."
            ) from error
        if destination != address.address:
            return None
        details = self._request(
            "POST",
            "/wallet/gettransactioninfobyid",
            json={"value": transaction_id},
        )
        block_number = details.get("blockNumber")
        if (
            isinstance(block_number, int)
            and not isinstance(block_number, bool)
            and (block_number < first_block or block_number > current_block)
        ):
            return None
        sender_blacklisted = self._is_tether_blacklisted(sender)
        recipient_blacklisted = self._is_tether_blacklisted(destination)
        confirmations = (
            max(0, current_block - block_number + 1)
            if isinstance(block_number, int) and not isinstance(block_number, bool)
            else 0
        )
        return ChainTransfer(
            transaction_id=str(transaction_id),
            address=address.address,
            amount_atomic=amount,
            confirmations=confirmations,
            contract_address=contract_address,
            sender=str(sender),
            recipient=str(destination),
            blacklisted=sender_blacklisted or recipient_blacklisted,
        )

    def wallet_balance(self) -> int:
        total = 0
        for address in DepositAddress.objects.filter(chain=self.chain).iterator():
            owner_address = to_hex_address(address.address)
            parameter = owner_address[-40:].rjust(64, "0")
            for contract in settings.TRC20_CONTRACT_WHITELIST:
                payload = self._request(
                    "POST",
                    "/wallet/triggerconstantcontract",
                    json={
                        "owner_address": owner_address,
                        "contract_address": to_hex_address(contract),
                        "function_selector": "balanceOf(address)",
                        "parameter": parameter,
                        "visible": False,
                    },
                )
                if not isinstance(payload, dict):
                    raise ProviderError(
                        "TronGrid returned an invalid TRC-20 wallet balance."
                    )
                call_result = payload.get("result")
                if (
                    not isinstance(call_result, dict)
                    or call_result.get("result") is not True
                ):
                    raise ProviderError(
                        "TronGrid could not read a TRC-20 wallet balance."
                    )
                results = payload.get("constant_result")
                if (
                    not isinstance(results, list)
                    or not results
                    or not isinstance(results[0], str)
                ):
                    raise ProviderError("TronGrid returned no TRC-20 wallet balance.")
                try:
                    balance = int(results[0], 16)
                except ValueError as error:
                    raise ProviderError(
                        "TronGrid returned an invalid TRC-20 wallet balance."
                    ) from error
                if balance < 0:
                    raise ProviderError("TronGrid returned a negative token balance.")
                total += balance
        return total

    def credit_amount(self, transfer) -> int:
        if transfer.contract_address.lower() not in {
            contract.lower() for contract in settings.TRC20_CONTRACT_WHITELIST
        }:
            raise ProviderError("Transfer token contract is not allowlisted.")
        amount = transfer.amount_atomic
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ProviderError("TronGrid returned an invalid token amount.")
        return amount
