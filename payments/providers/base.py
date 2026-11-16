from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ChainTransfer:
    transaction_id: str
    address: str
    amount_atomic: int
    confirmations: int
    contract_address: str = ""
    sender: str = ""
    recipient: str = ""
    blacklisted: bool = False


class ChainProvider(ABC):
    chain: str
    decimals: int
    supports_deposit = False
    supports_withdrawal = False
    supports_balance = False
    # Kept for adapters written against the original plural attribute.
    supports_withdrawals = False
    observations_are_complete = False

    @abstractmethod
    def new_address(self, user, chain: str) -> tuple[str, str]:
        """Return the deposit address and provider reference."""

    @abstractmethod
    def poll(self) -> Iterable[ChainTransfer]:
        """Return newly observed inbound transfers for the configured chain."""

    @abstractmethod
    def credit_amount(self, transfer: ChainTransfer) -> int:
        """Return a validated positive amount in the chain's atomic units."""

    def wallet_balance(self) -> int:
        raise BalanceAdapterUnavailable(
            f"{self.chain} provider does not expose a wallet balance adapter."
        )

    def sweep_to_hot(self) -> int:
        raise ProviderError(f"{self.chain} provider does not support wallet sweeps.")

    def send_withdrawal(
        self,
        destination: str,
        amount_base_units: int,
        idempotency_key: str,
    ) -> str:
        raise ProviderError("Outbound transfers are not supported by this provider.")


class ProviderError(RuntimeError):
    pass


class BalanceAdapterUnavailable(ProviderError):
    pass
