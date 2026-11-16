from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from payments.models import Chain
from payments.providers.base import ChainProvider
from payments.providers.fake import FakeProvider


def get_chain_provider(chain: str) -> ChainProvider:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    provider_name = settings.CHAIN_PROVIDERS.get(chain, "fake")
    if provider_name == "fake":
        return FakeProvider(chain)
    if provider_name == "btcpay":
        from payments.providers.btcpay import BTCPayProvider

        if chain not in {Chain.BTC, Chain.LTC}:
            raise ImproperlyConfigured("BTCPay is configured for an unsupported chain.")
        return BTCPayProvider(chain)
    if provider_name == "trongrid":
        from payments.providers.trongrid import TronGridProvider

        if chain != Chain.TRC20:
            raise ImproperlyConfigured("TronGrid can only serve the TRC-20 chain.")
        return TronGridProvider()
    if provider_name == "monero_wallet_rpc":
        from payments.providers.monero import MoneroWalletProvider

        if chain != Chain.XMR:
            raise ImproperlyConfigured("monero-wallet-rpc can only serve XMR.")
        return MoneroWalletProvider()
    raise ImproperlyConfigured(f"Unknown provider configured for {chain}.")
