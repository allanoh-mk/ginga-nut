from django.conf import settings
from django.db import transaction

from payments.models import Chain, Deposit, DepositEvent


@transaction.atomic
def promote_deposit(deposit: Deposit) -> Deposit:
    locked = Deposit.objects.select_for_update().get(pk=deposit.pk)
    if locked.state not in {Deposit.State.SEEN, Deposit.State.CONFIRMING}:
        return locked

    known_contract = (
        locked.address.chain != Chain.TRC20
        or locked.contract_address.lower()
        in {contract.lower() for contract in settings.TRC20_CONTRACT_WHITELIST}
    )
    required = settings.MARKET_CHAIN_CONFIRMATIONS[locked.address.chain]
    if not known_contract or locked.confirmations == 0:
        target = Deposit.State.SEEN
    elif locked.blacklisted or locked.confirmations < required:
        target = Deposit.State.CONFIRMING
    else:
        target = Deposit.State.CONFIRMED

    if target != locked.state:
        previous = locked.state
        locked.state = target
        locked.save(update_fields=("state", "updated_at"))
        DepositEvent.objects.create(
            deposit=locked,
            from_state=previous,
            to_state=target,
            confirmations=locked.confirmations,
            reason="confirmation_depth"
            if target == Deposit.State.CONFIRMED
            else "confirming",
        )
    return locked
