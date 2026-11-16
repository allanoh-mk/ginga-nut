import hashlib
from collections.abc import Iterable
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from payments.models import (
    Chain,
    DepositAddress,
    MoneroOrderEscrow,
    RateTick,
)
from payments.providers.base import (
    BalanceAdapterUnavailable,
    ChainProvider,
    ChainTransfer,
    ProviderError,
)
from payments.providers.rates import RATE_SOURCE_NAMES

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_ALLOWED_METHODS = {
    "reserve": {"get_balance"},
    "hot": {
        "create_address",
        "get_address",
        "get_balance",
        "get_transfers",
        "sweep_all",
    },
    "payout": {"transfer"},
}
_RPC_SETTINGS = {
    "reserve": (
        "MONERO_RESERVE_WALLET_RPC_URL",
        "MONERO_RESERVE_WALLET_RPC_USER",
        "MONERO_RESERVE_WALLET_RPC_PASSWORD",
    ),
    "hot": (
        "MONERO_HOT_WALLET_RPC_URL",
        "MONERO_HOT_WALLET_RPC_USER",
        "MONERO_HOT_WALLET_RPC_PASSWORD",
    ),
    "payout": (
        "MONERO_PAYOUT_WALLET_RPC_URL",
        "MONERO_PAYOUT_WALLET_RPC_USER",
        "MONERO_PAYOUT_WALLET_RPC_PASSWORD",
    ),
}


class MoneroWalletProvider(ChainProvider):
    observations_are_complete = True
    supports_deposit = True
    supports_balance = True
    supports_withdrawal = True
    supports_withdrawals = True

    def __init__(self) -> None:
        self.chain = Chain.XMR
        self.decimals = 12
        self.sessions: dict[str, requests.Session] = {}
        self.urls: dict[str, str] = {}
        for role, (
            url_setting,
            user_setting,
            password_setting,
        ) in _RPC_SETTINGS.items():
            url = getattr(settings, url_setting, "").strip()
            if not url:
                raise ImproperlyConfigured(f"{url_setting} is required.")
            parsed = urlparse(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ImproperlyConfigured(f"{url_setting} must be a valid HTTP URL.")
            if settings.ONION_ONLY and parsed.hostname not in _LOCAL_HOSTS:
                raise ImproperlyConfigured(
                    f"Production {url_setting} must point to a localhost wallet RPC."
                )
            self.urls[role] = url.rstrip("/")
            session = requests.Session()
            session.trust_env = False
            username = getattr(settings, user_setting, "")
            password = getattr(settings, password_setting, "")
            if bool(username) != bool(password):
                raise ImproperlyConfigured(
                    f"{user_setting} and {password_setting} must be configured together."
                )
            if settings.ONION_ONLY and (not username or not password):
                raise ImproperlyConfigured(
                    f"Production requires authentication for the {role} wallet RPC."
                )
            if username:
                session.auth = (username, password)
            self.sessions[role] = session

        if len(set(self.urls.values())) != len(self.urls):
            raise ImproperlyConfigured(
                "Monero reserve, hot, and payout wallet RPC endpoints must be distinct."
            )
        self.daemon_session = requests.Session()
        self.daemon_session.trust_env = False

    def _rpc(self, role: str, method: str, params: dict) -> dict:
        if role not in _ALLOWED_METHODS or method not in _ALLOWED_METHODS[role]:
            raise ProviderError(f"{role} Monero wallet does not permit {method}.")
        try:
            response = self.sessions[role].post(
                self.urls[role],
                json={
                    "jsonrpc": "2.0",
                    "id": "kola-market",
                    "method": method,
                    "params": params,
                },
                timeout=settings.RATE_FEED_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise ProviderError(f"Monero {role} wallet RPC request failed.") from error
        if not isinstance(payload, dict) or payload.get("error"):
            raise ProviderError(f"Monero {role} wallet RPC returned an error.")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ProviderError(
                f"Monero {role} wallet RPC returned an invalid response."
            )
        return result

    @staticmethod
    def _balance(result: dict) -> int:
        amount = result.get("balance")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ProviderError("Monero wallet RPC returned an invalid balance.")
        return amount

    def validate_at_startup(self) -> None:
        monerod_url = urlparse(settings.MONEROD_RPC_URL)
        if (
            monerod_url.scheme not in {"http", "https"}
            or monerod_url.hostname not in _LOCAL_HOSTS
        ):
            raise ImproperlyConfigured(
                "MONEROD_RPC_URL must point to a localhost RPC endpoint."
            )
        try:
            response = self.daemon_session.post(
                settings.MONEROD_RPC_URL,
                json={},
                timeout=settings.RATE_FEED_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            daemon_info = response.json()
        except requests.RequestException as error:
            raise ProviderError("Local monerod RPC health check failed.") from error
        height = daemon_info.get("height") if isinstance(daemon_info, dict) else None
        if isinstance(height, bool) or not isinstance(height, int):
            raise ProviderError("Local monerod RPC returned invalid node information.")
        self._balance(self._rpc("reserve", "get_balance", {"account_index": 0}))

    def wallet_balance(self) -> int:
        reserve = self._balance(
            self._rpc("reserve", "get_balance", {"account_index": 0})
        )
        hot = self._balance(self._rpc("hot", "get_balance", {"account_index": 0}))
        multisig = 0
        active_escrows = MoneroOrderEscrow.objects.filter(
            state__in=(
                MoneroOrderEscrow.State.FUNDED,
                MoneroOrderEscrow.State.SETTLEMENT_PENDING,
                MoneroOrderEscrow.State.CANCELLATION_PENDING,
                MoneroOrderEscrow.State.REVIEW,
                MoneroOrderEscrow.State.AWAITING_FUNDING,
                MoneroOrderEscrow.State.CANCELLED,
                MoneroOrderEscrow.State.FAILED,
            )
        ).exists()
        if active_escrows:
            from payments.monero_escrow_gateway import multisig_escrow_balance_atomic

            try:
                multisig = multisig_escrow_balance_atomic()
            except ImproperlyConfigured as error:
                raise BalanceAdapterUnavailable(
                    "Monero multisig escrow balance adapter is not configured."
                ) from error
        return reserve + hot + multisig

    def new_address(self, user, chain: str) -> tuple[str, str]:
        if chain != self.chain:
            raise ValueError("Provider chain does not match the requested chain.")
        label = hashlib.sha256(f"{user.pk}:{chain}".encode()).hexdigest()[:24]
        result = self._rpc(
            "hot",
            "create_address",
            {"account_index": 0, "label": label},
        )
        address = result.get("address")
        index = result.get("address_index")
        if not address or isinstance(index, bool) or not isinstance(index, int):
            raise ProviderError("Monero wallet RPC did not return a subaddress.")
        return address, str(index)

    def poll(self) -> Iterable[ChainTransfer]:
        for address in DepositAddress.objects.filter(chain=self.chain).iterator():
            try:
                address_index = int(address.provider_reference)
            except ValueError as error:
                raise ProviderError(
                    "Monero address is missing its subaddress index."
                ) from error
            result = self._rpc(
                "hot",
                "get_transfers",
                {
                    "in": True,
                    "pool": True,
                    "account_index": 0,
                    "subaddr_indices": [address_index],
                },
            )
            for transfer in result.get("in", []) + result.get("pool", []):
                txid = transfer.get("txid")
                amount = transfer.get("amount")
                if not txid or isinstance(amount, bool) or not isinstance(amount, int):
                    raise ProviderError(
                        "Monero wallet RPC returned invalid transfer data."
                    )
                yield ChainTransfer(
                    transaction_id=str(txid),
                    address=address.address,
                    amount_atomic=amount,
                    confirmations=int(transfer.get("confirmations", 0)),
                )

    def sweep_to_hot(self) -> int:
        indices = set()
        for reference in DepositAddress.objects.filter(chain=self.chain).values_list(
            "provider_reference", flat=True
        ):
            try:
                index = int(reference)
            except (TypeError, ValueError) as error:
                raise ProviderError(
                    "Monero deposit address is missing its subaddress index."
                ) from error
            if index < 0:
                raise ProviderError("Monero subaddress index cannot be negative.")
            indices.add(index)
        if not indices:
            return 0

        indices = sorted(indices)
        balance = self._rpc(
            "hot",
            "get_balance",
            {
                "account_index": 0,
                "address_indices": indices,
            },
        )
        unlocked = balance.get("unlocked_balance")
        if isinstance(unlocked, bool) or not isinstance(unlocked, int) or unlocked < 0:
            raise ProviderError(
                "Monero wallet RPC returned an invalid unlocked balance."
            )
        if unlocked == 0:
            return 0

        primary = self._rpc(
            "hot",
            "get_address",
            {"account_index": 0, "address_index": 0},
        ).get("address")
        if not primary:
            raise ProviderError("Monero hot wallet did not return its primary address.")
        result = self._rpc(
            "hot",
            "sweep_all",
            {
                "account_index": 0,
                "subaddr_indices": indices,
                "address": primary,
                "priority": 1,
                "get_tx_keys": False,
            },
        )
        tx_hashes = result.get("tx_hash_list", [])
        if not isinstance(tx_hashes, list) or any(
            not isinstance(tx_hash, str) or not tx_hash for tx_hash in tx_hashes
        ):
            raise ProviderError("Monero sweep returned invalid transaction references.")
        return len(tx_hashes)

    def credit_amount(self, transfer: ChainTransfer) -> int:
        amount = transfer.amount_atomic
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ProviderError("Monero wallet RPC returned an invalid amount.")
        return amount

    def _base_units_to_atomic(self, amount_base_units: int) -> int:
        now = timezone.now()
        ticks = {
            source: RateTick.objects.filter(chain=self.chain, source=source)
            .order_by("-observed_at", "-pk")
            .first()
            for source in RATE_SOURCE_NAMES
        }
        if any(tick is None for tick in ticks.values()):
            raise ProviderError("A current XMR conversion rate is required to send.")
        if any(
            (now - tick.observed_at).total_seconds() > settings.RATE_FEED_STALE_SECONDS
            for tick in ticks.values()
            if tick
        ):
            raise ProviderError("XMR conversion rate is stale; payout is paused.")
        tick_values = [tick.base_units_per_coin for tick in ticks.values() if tick]
        if min(tick_values) <= 0:
            raise ProviderError("XMR conversion rate must be positive.")
        lower, upper = sorted(tick_values)
        if (upper - lower) * 100 > lower:
            raise ProviderError("XMR conversion sources diverge; payout is paused.")
        return amount_base_units * (10**self.decimals) // min(tick_values)

    def send_withdrawal(
        self,
        destination: str,
        amount_base_units: int,
        idempotency_key: str,
    ) -> str:
        if (
            not destination
            or isinstance(amount_base_units, bool)
            or not isinstance(amount_base_units, int)
            or amount_base_units <= 0
            or not idempotency_key
        ):
            raise ValueError(
                "Monero payout requires a destination and positive amount."
            )
        amount_atomic = self._base_units_to_atomic(amount_base_units)
        if amount_atomic <= 0:
            raise ProviderError("Payout converts to less than one atomic XMR unit.")
        result = self._rpc(
            "payout",
            "transfer",
            {
                "account_index": 0,
                "destinations": [{"address": destination, "amount": amount_atomic}],
                "priority": 2,
                "get_tx_key": False,
            },
        )
        transaction_id = result.get("tx_hash")
        if not transaction_id:
            raise ProviderError("Monero payout wallet returned no transaction hash.")
        return str(transaction_id)
