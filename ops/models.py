from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ImmutableSnapshotQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Reserve snapshots are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Reserve snapshots are immutable.")


class ImmutableIntegrityRunQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Reserve integrity runs are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Reserve integrity runs are immutable.")


class ReserveIntegrityRun(models.Model):
    results = models.JSONField(default=dict)
    shortfall_chains = models.JSONField(default=list)
    unmeasurable_chains = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableIntegrityRunQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError("Reserve integrity runs are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Reserve integrity runs are immutable.")

    def __str__(self) -> str:
        return f"Reserve integrity run {self.pk} at {self.created_at}"


class ReserveSnapshot(models.Model):
    liability_base_units = models.PositiveBigIntegerField()
    hot_balance_base_units = models.PositiveBigIntegerField()
    cold_balance_base_units = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableSnapshotQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")

    @property
    def reserve_total_base_units(self) -> int:
        return self.hot_balance_base_units + self.cold_balance_base_units

    @property
    def ratio(self) -> Decimal | None:
        if self.liability_base_units == 0:
            return None
        return Decimal(self.reserve_total_base_units) / Decimal(
            self.liability_base_units
        )

    @property
    def below_warning_threshold(self) -> bool:
        return (
            self.liability_base_units > 0
            and self.reserve_total_base_units * 10 < self.liability_base_units * 13
        )

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError("Reserve snapshots are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Reserve snapshots are immutable.")

    def __str__(self) -> str:
        return f"Reserve snapshot {self.pk} at {self.created_at}"


class MarketSwitch(models.Model):
    class Key(models.TextChoices):
        GLOBAL = "global", "Global"

    key = models.CharField(
        max_length=16,
        choices=Key.choices,
        primary_key=True,
        default=Key.GLOBAL,
    )
    withdrawals_enabled = models.BooleanField(default=True)
    new_orders_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "Market operational switches"


class MarketSwitchChangeQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Market switch audit records are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Market switch audit records are immutable.")


class MarketSwitchChange(models.Model):
    feature = models.CharField(max_length=32)
    enabled = models.BooleanField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_switch_changes",
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MarketSwitchChangeQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValidationError("Market switch audit records are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Market switch audit records are immutable.")
