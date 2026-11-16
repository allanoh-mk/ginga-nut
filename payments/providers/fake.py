from collections.abc import Iterable

from django.conf import settings

from payments.models import Chain
from payments.providers.base import ChainProvider, ChainTransfer


class FakeProvider(ChainProvider):
    supports_deposit = True
    supports_withdrawal = True
    supports_balance = True
    supports_withdrawals = True
    _wallet_balances_atomic: dict[str, int] = {}
    _DECIMALS = {
        Chain.BTC: 8,
        Chain.LTC: 8,
        Chain.TRC20: settings.TRC20_TOKEN_DECIMALS,
        Chain.XMR: 12,
    }

    def __init__(self, chain: str) -> None:
        if chain not in self._DECIMALS:
            raise ValueError(f"Unsupported chain: {chain}")
        self.chain = chain
        self.decimals = self._DECIMALS[chain]
        self._transfers: list[ChainTransfer] = []
        self.last_sweep_destination = ""

    def new_address(self, user, chain: str) -> tuple[str, str]:
        if chain != self.chain:
            raise ValueError("Provider chain does not match the requested chain.")
        return f"fake-{chain.lower()}-{user.pk}", f"fake-user-{user.pk}"

    def poll(self) -> Iterable[ChainTransfer]:
        return tuple(self._transfers)

    def wallet_balance(self) -> int:
        return self._wallet_balances_atomic.get(self.chain, 0)

    def set_wallet_balance(self, amount_atomic: int) -> None:
        if (
            isinstance(amount_atomic, bool)
            or not isinstance(amount_atomic, int)
            or amount_atomic < 0
        ):
            raise ValueError("Fake wallet balance must be a non-negative integer.")
        self._wallet_balances_atomic[self.chain] = amount_atomic

    def sweep_to_hot(self) -> int:
        self.last_sweep_destination = f"fake-hot-{self.chain.lower()}"
        return 0

    def credit_amount(self, transfer: ChainTransfer) -> int:
        if (
            isinstance(transfer.amount_atomic, bool)
            or not isinstance(transfer.amount_atomic, int)
            or transfer.amount_atomic <= 0
        ):
            raise ValueError("Provider transfer amount must be positive.")
        return transfer.amount_atomic

    def add_transfer(self, transfer: ChainTransfer) -> None:
        self._transfers.append(transfer)

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
                "Fake withdrawal requires a destination and positive amount."
            )
        return f"fake-withdrawal-{idempotency_key}"
