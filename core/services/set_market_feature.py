from django.core.exceptions import ValidationError
from django.db import transaction

from core.services.is_market_feature_enabled import FEATURE_FIELDS
from ops.models import MarketSwitch, MarketSwitchChange


@transaction.atomic
def set_market_feature(
    feature: str,
    enabled: bool | None,
    *,
    actor=None,
    reason: str = "",
) -> MarketSwitch:
    field = FEATURE_FIELDS.get(feature)
    if field is None:
        raise ValueError(f"Unknown market feature: {feature}")
    if enabled is not None and not isinstance(enabled, bool):
        raise TypeError("Feature state must be a boolean or None to toggle.")
    if enabled is None and actor is None:
        raise ValidationError("An actor is required to toggle a market feature.")
    normalized_reason = reason.strip()
    if actor is not None and not normalized_reason:
        raise ValidationError("A reason is required for a staff market switch change.")
    switch, _ = MarketSwitch.objects.select_for_update().get_or_create(
        pk=MarketSwitch.Key.GLOBAL
    )
    if enabled is None:
        enabled = not getattr(switch, field)
    setattr(switch, field, enabled)
    switch.save(update_fields=(field, "updated_at"))
    if actor is not None:
        MarketSwitchChange.objects.create(
            feature=feature,
            enabled=enabled,
            actor=actor,
            reason=normalized_reason,
        )
    return switch
