from ledger.models import Account


def lock_order_accounts(*accounts: Account) -> dict[int, Account]:
    account_ids = sorted({account.pk for account in accounts})
    locked_accounts = {
        account.pk: account
        for account in Account.objects.select_for_update()
        .filter(pk__in=account_ids)
        .order_by("pk")
    }
    if len(locked_accounts) != len(account_ids):
        raise Account.DoesNotExist("An order ledger account no longer exists.")
    return locked_accounts
