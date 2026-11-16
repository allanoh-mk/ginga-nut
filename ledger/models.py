from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum


class Account(models.Model):
    class Kind(models.TextChoices):
        EXTERNAL = "external", "External"
        USER_AVAILABLE = "user_available", "User available"
        USER_ESCROW = "user_escrow", "User escrow"
        VENDOR_AVAILABLE = "vendor_available", "Vendor available"
        VENDOR_BOND = "vendor_bond", "Vendor bond"
        MARKET_FEE = "market_fee", "Market fee"
        MARKET_SPREAD = "market_spread", "Market spread"
        TREASURY = "treasury", "Treasury"
        SUSPENSE = "suspense", "Suspense"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ledger_accounts",
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "kind"),
                condition=models.Q(owner__isnull=False),
                name="ledger_unique_owner_account_kind",
            )
        ]

    @property
    def balance(self) -> int:
        return self.entries.aggregate(total=Sum("amount"))["total"] or 0

    def __str__(self) -> str:
        return f"{self.kind} account {self.pk}"


class ImmutableLedgerEntryQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Ledger entries are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ledger entries are immutable.")


class LedgerEntry(models.Model):
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="entries",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    amount = models.BigIntegerField()
    ref = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    objects = ImmutableLedgerEntryQuerySet.as_manager()

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError("Ledger entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError("Ledger entries are immutable.")

    def __str__(self) -> str:
        return f"{self.account_id}: {self.amount} ({self.ref})"
