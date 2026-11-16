import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Chain(models.TextChoices):
    BTC = "BTC", "BTC"
    LTC = "LTC", "LTC"
    TRC20 = "TRC20", "TRC-20"
    XMR = "XMR", "XMR"


class ImmutablePaymentQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Payment audit records are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Payment audit records are immutable.")


class ChainPollWatermark(models.Model):
    provider = models.CharField(max_length=32)
    chain = models.CharField(max_length=8, choices=Chain.choices)
    last_block = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "chain"),
                name="payments_unique_chain_poll_watermark",
            )
        ]


class DepositAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deposit_addresses",
    )
    chain = models.CharField(max_length=8, choices=Chain.choices)
    address = models.CharField(max_length=255)
    provider_reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutablePaymentQuerySet.as_manager()

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValidationError("Deposit addresses are permanent.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Deposit addresses are permanent.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "chain"),
                name="payments_one_deposit_address_per_user_chain",
            ),
            models.UniqueConstraint(
                fields=("chain", "address"),
                name="payments_unique_chain_address",
            ),
        ]


class WalletLink(models.Model):
    class Chain(models.TextChoices):
        TRC20 = "TRC20", "TRON / TRC-20"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet_links",
    )
    chain = models.CharField(max_length=8, choices=Chain.choices)
    address = models.CharField(max_length=34)
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-linked_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("chain", "address"),
                condition=models.Q(unlinked_at__isnull=True),
                name="payments_one_active_wallet_owner",
            )
        ]
        indexes = [
            models.Index(fields=("user", "chain", "unlinked_at")),
        ]

    def __str__(self) -> str:
        return f"{self.chain} wallet for {self.user_id}"


class WalletLinkChallenge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet_link_challenges",
    )
    chain = models.CharField(
        max_length=8,
        choices=WalletLink.Chain.choices,
    )
    address = models.CharField(max_length=34)
    nonce = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def message_to_sign(self) -> str:
        return (
            "Kola Market wallet link v1\n"
            f"Account ID: {self.user_id}\n"
            f"Chain: {self.chain}\n"
            f"Address: {self.address}\n"
            f"Nonce: {self.nonce}\n"
            f"Expires (Unix UTC): {int(self.expires_at.timestamp())}\n"
        )


class PayoutAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_addresses",
    )
    chain = models.CharField(max_length=8, choices=Chain.choices)
    address = models.CharField(max_length=255)
    label = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    available_after = models.DateTimeField(db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "chain", "address"),
                condition=models.Q(deleted_at__isnull=True),
                name="payments_unique_active_payout_address",
            )
        ]
        indexes = [
            models.Index(fields=("user", "chain", "deleted_at", "available_after")),
        ]

    def __str__(self) -> str:
        return f"{self.chain} payout address ({self.label})"


class PayoutAddressChallenge(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_address_challenges",
    )
    payout_address = models.ForeignKey(
        PayoutAddress,
        on_delete=models.PROTECT,
        related_name="ownership_challenges",
    )
    nonce = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def message_to_sign(self) -> str:
        return (
            "Kola Market payout address ownership v1\n"
            f"Account ID: {self.user_id}\n"
            f"Chain: {self.payout_address.chain}\n"
            f"Address: {self.payout_address.address}\n"
            f"Nonce: {self.nonce}\n"
            f"Expires (Unix UTC): {int(self.expires_at.timestamp())}\n"
        )


class RateTick(models.Model):
    chain = models.CharField(max_length=8, choices=Chain.choices)
    source = models.CharField(max_length=32)
    base_units_per_coin = models.PositiveBigIntegerField()
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-observed_at", "-pk")

    objects = ImmutablePaymentQuerySet.as_manager()

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValidationError("Rate ticks are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Rate ticks are immutable.")


class RateQuote(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rate_quotes",
    )
    chain = models.CharField(max_length=8, choices=Chain.choices)
    source_a = models.ForeignKey(
        RateTick,
        on_delete=models.PROTECT,
        related_name="quotes_as_source_a",
    )
    source_b = models.ForeignKey(
        RateTick,
        on_delete=models.PROTECT,
        related_name="quotes_as_source_b",
    )
    base_units_per_coin = models.PositiveBigIntegerField()
    amount_min_atomic = models.PositiveBigIntegerField()
    amount_max_atomic = models.PositiveBigIntegerField()
    locked_until = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    amount_max_atomic__gte=models.F("amount_min_atomic")
                ),
                name="payments_quote_amount_band_ordered",
            )
        ]

    objects = ImmutablePaymentQuerySet.as_manager()

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            previous = RateQuote.objects.get(pk=self.pk)
            changed = {
                field
                for field in (
                    "user_id",
                    "chain",
                    "source_a_id",
                    "source_b_id",
                    "base_units_per_coin",
                    "amount_min_atomic",
                    "amount_max_atomic",
                    "locked_until",
                    "created_at",
                )
                if getattr(previous, field) != getattr(self, field)
            }
            if changed or (
                previous.consumed_at is not None
                and self.consumed_at != previous.consumed_at
            ):
                raise ValidationError("Quote terms are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Rate quotes are immutable.")


class Deposit(models.Model):
    class State(models.TextChoices):
        SEEN = "seen", "Seen"
        CONFIRMING = "confirming", "Confirming"
        CONFIRMED = "confirmed", "Confirmed"
        CREDITED = "credited", "Credited"
        REVERSED = "reversed", "Reversed"
        ORPHANED = "orphaned", "Orphaned"

    address = models.ForeignKey(
        DepositAddress,
        on_delete=models.PROTECT,
        related_name="deposits",
    )
    transaction_id = models.CharField(max_length=255)
    contract_address = models.CharField(max_length=128, blank=True)
    amount_atomic = models.PositiveBigIntegerField()
    confirmations = models.PositiveIntegerField(default=0)
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.SEEN,
        db_index=True,
    )
    blacklisted = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(default=timezone.now)
    quote = models.ForeignKey(
        RateQuote,
        on_delete=models.PROTECT,
        related_name="deposits",
        null=True,
        blank=True,
    )
    base_amount = models.PositiveBigIntegerField(default=0)
    support_flag = models.BooleanField(default=False)
    conversion_processed_at = models.DateTimeField(null=True, blank=True)
    credited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("address", "transaction_id", "contract_address"),
                name="payments_unique_deposit_transaction",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_atomic__gt=0),
                name="payments_deposit_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.address.chain} deposit {self.transaction_id}"


class DepositEvent(models.Model):
    deposit = models.ForeignKey(
        Deposit,
        on_delete=models.PROTECT,
        related_name="events",
    )
    from_state = models.CharField(
        max_length=16,
        choices=Deposit.State.choices,
        blank=True,
    )
    to_state = models.CharField(max_length=16, choices=Deposit.State.choices)
    confirmations = models.PositiveIntegerField()
    reason = models.CharField(max_length=48)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")


class Withdrawal(models.Model):
    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        MANUAL_APPROVAL = "manual_approval", "Manual approval required"
        APPROVED = "approved", "Approved"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="withdrawals",
    )
    chain = models.CharField(max_length=8, choices=Chain.choices)
    destination = models.CharField(max_length=255)
    amount_base_units = models.PositiveBigIntegerField()
    fee_base_units = models.PositiveBigIntegerField()
    idempotency_key = models.CharField(max_length=128)
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.QUEUED,
        db_index=True,
    )
    provider_reference = models.CharField(max_length=255, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "idempotency_key"),
                name="payments_unique_withdrawal_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_base_units__gt=0),
                name="payments_withdrawal_amount_positive",
            ),
        ]

    @property
    def terminal(self) -> bool:
        return self.state in {
            self.State.COMPLETED,
            self.State.FAILED,
            self.State.REJECTED,
        }

    @property
    def net_amount_base_units(self) -> int:
        return self.amount_base_units - self.fee_base_units

    def mark_completed(self) -> None:
        self.state = self.State.COMPLETED
        self.completed_at = timezone.now()

    def __str__(self) -> str:
        return f"Withdrawal {self.pk} ({self.state})"


class MoneroOrderEscrow(models.Model):
    class State(models.TextChoices):
        REQUESTED = "requested", "Requested"
        AWAITING_SIGNERS = "awaiting_signers", "Awaiting participant setup"
        AWAITING_FUNDING = "awaiting_funding", "Awaiting XMR funding"
        FUNDED = "funded", "Funded"
        SETTLEMENT_PENDING = "settlement_pending", "Awaiting multisig settlement"
        CANCELLATION_PENDING = "cancellation_pending", "Awaiting escrow cancellation"
        SETTLED = "settled", "Settled"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"
        REVIEW = "review", "Requires operator review"

    class SettlementAction(models.TextChoices):
        RELEASE = "release", "Release to marketplace"
        REFUND = "refund", "Refund to marketplace balance"
        PARTIAL = "partial", "Partial release and refund"

    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="monero_escrow",
    )
    rate_quote = models.ForeignKey(
        RateQuote,
        on_delete=models.PROTECT,
        related_name="monero_order_escrows",
        null=True,
        blank=True,
    )
    state = models.CharField(
        max_length=24,
        choices=State.choices,
        default=State.REQUESTED,
        db_index=True,
    )
    external_id = models.CharField(max_length=128, blank=True)
    deposit_address = models.CharField(max_length=128, blank=True)
    expected_amount_atomic = models.PositiveBigIntegerField(default=0)
    received_amount_atomic = models.PositiveBigIntegerField(default=0)
    settlement_action = models.CharField(
        max_length=8,
        choices=SettlementAction.choices,
        blank=True,
    )
    settlement_release_base_units = models.PositiveBigIntegerField(
        null=True,
        blank=True,
    )
    cancellation_reason = models.CharField(max_length=16, blank=True)
    last_event_sequence = models.PositiveBigIntegerField(default=0)
    settlement_transaction_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("external_id",),
                condition=~models.Q(external_id=""),
                name="payments_monero_escrow_external_id_unique",
            ),
        ]


class MoneroOrderEscrowEventQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Monero escrow events are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Monero escrow events are immutable.")


class MoneroOrderEscrowEvent(models.Model):
    escrow = models.ForeignKey(
        MoneroOrderEscrow,
        on_delete=models.PROTECT,
        related_name="events",
    )
    event_id = models.CharField(max_length=128, unique=True)
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=32)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MoneroOrderEscrowEventQuerySet.as_manager()

    class Meta:
        ordering = ("sequence", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("escrow", "sequence"),
                name="payments_monero_escrow_event_sequence_unique",
            )
        ]

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValidationError("Monero escrow events are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Monero escrow events are immutable.")
