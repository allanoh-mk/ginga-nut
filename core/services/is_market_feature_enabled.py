from ops.models import MarketSwitch

FEATURE_FIELDS = {
    "withdrawals": "withdrawals_enabled",
    "new_orders": "new_orders_enabled",
}


def is_market_feature_enabled(feature: str) -> bool:
    field = FEATURE_FIELDS.get(feature)
    if field is None:
        raise ValueError(f"Unknown market feature: {feature}")
    enabled = (
        MarketSwitch.objects.filter(pk=MarketSwitch.Key.GLOBAL)
        .values_list(
            field,
            flat=True,
        )
        .first()
    )
    return enabled if enabled is not None else True
