from django.db import transaction

from core.services.reverse_deposit import reverse_deposit
from payments.models import Chain, Deposit


@transaction.atomic
def orphan_unseen_deposits(
    chain: str,
    observed_keys: set[tuple[str, str, str]],
) -> list[Deposit]:
    if chain not in Chain.values:
        raise ValueError(f"Unsupported chain: {chain}")
    unseen = []
    for deposit in (
        Deposit.objects.select_for_update()
        .filter(
            address__chain=chain,
        )
        .exclude(state__in=(Deposit.State.REVERSED, Deposit.State.ORPHANED))
    ):
        identity = (
            deposit.address.address,
            deposit.transaction_id,
            deposit.contract_address,
        )
        if identity in observed_keys:
            continue
        deposit.confirmations = 0
        deposit.save(update_fields=("confirmations", "updated_at"))
        unseen.append(reverse_deposit(deposit, "txid_disappeared"))
    return unseen
