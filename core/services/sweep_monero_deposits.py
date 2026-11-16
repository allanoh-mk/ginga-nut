import logging

from payments.models import Chain
from payments.providers import get_chain_provider

logger = logging.getLogger(__name__)


def sweep_monero_deposits() -> int:
    provider = get_chain_provider(Chain.XMR)
    transaction_count = provider.sweep_to_hot()
    logger.info(
        "Completed Monero deposit sweep to hot wallet.",
        extra={"transaction_count": transaction_count},
    )
    return transaction_count
