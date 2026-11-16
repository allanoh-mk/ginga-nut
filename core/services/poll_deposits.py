from core.services.orphan_unseen_deposits import orphan_unseen_deposits
from core.services.promote_deposit import promote_deposit
from core.services.record_deposit_transfer import record_deposit_transfer
from payments.models import Chain
from payments.providers import get_chain_provider


def poll_deposits(chain: str) -> list:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    provider = get_chain_provider(chain)
    transfers = list(provider.poll())
    observed_keys = {
        (transfer.address, transfer.transaction_id, transfer.contract_address)
        for transfer in transfers
    }
    recorded = []
    for transfer in transfers:
        deposit = record_deposit_transfer(chain, transfer, provider)
        recorded.append(promote_deposit(deposit))
    if provider.observations_are_complete:
        orphan_unseen_deposits(chain, observed_keys)
    commit_poll = getattr(provider, "commit_poll", None)
    if callable(commit_poll):
        commit_poll()
    return recorded
