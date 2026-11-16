class InsufficientFunds(Exception):
    def __init__(self, account_id: int, available: int, requested: int) -> None:
        self.account_id = account_id
        self.available = available
        self.requested = requested
        super().__init__(
            f"Account {account_id} has {available} units; "
            f"{requested} units were requested."
        )


class LedgerImbalance(Exception):
    def __init__(self, total: int) -> None:
        self.total = total
        super().__init__(f"Ledger is unbalanced: global sum is {total} units.")
