from django.core.exceptions import ValidationError

MARKET_COMMISSION_PERCENT = 3


def calculate_market_commission(gross_base_units: int) -> tuple[int, int]:
    if isinstance(gross_base_units, bool) or not isinstance(gross_base_units, int):
        raise TypeError("Commission amount must be an integer.")
    if gross_base_units <= 0:
        raise ValueError("Commission amount must be positive.")
    fee = (gross_base_units * MARKET_COMMISSION_PERCENT + 99) // 100
    net = gross_base_units - fee
    if net <= 0:
        raise ValidationError(
            "The amount is too small to cover the 3% market commission."
        )
    return fee, net
