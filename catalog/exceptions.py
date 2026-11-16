class ListingUnavailable(Exception):
    pass


class InsufficientStock(Exception):
    def __init__(self, available: int, requested: int) -> None:
        self.available = available
        self.requested = requested
        super().__init__(
            f"Only {available} units are in stock; {requested} were requested."
        )
