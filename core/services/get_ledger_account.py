from django.contrib.auth import get_user_model
from django.db import transaction

from ledger.models import Account


@transaction.atomic
def get_ledger_account(kind: str, owner=None) -> Account:
    if owner is None:
        account = (
            Account.objects.filter(kind=kind, owner__isnull=True).order_by("pk").first()
        )
        if account is None:
            raise Account.DoesNotExist(f"System account {kind} has not been seeded.")
        return account
    locked_owner = get_user_model().objects.select_for_update().get(pk=owner.pk)
    account = Account.objects.filter(kind=kind, owner=locked_owner).first()
    if account is not None:
        return account
    return Account.objects.create(kind=kind, owner=locked_owner)
