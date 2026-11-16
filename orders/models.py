from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from orders.fields import EncryptedTextField
from orders.uploads import (
    evidence_upload_to,
    pack_photo_upload_to,
    validate_evidence_extension,
    validate_pack_photo_extension,
    validate_upload_size,
)


def _ensure_new_orders_enabled() -> None:
    from core.services.is_market_feature_enabled import is_market_feature_enabled

    if not is_market_feature_enabled("new_orders"):
        raise ValidationError("New orders are temporarily paused.")


class OrderQuerySet(models.QuerySet):
    def bulk_create(self, objs, *args, **kwargs):
        objects = list(objs)
        if objects:
            _ensure_new_orders_enabled()
        return super().bulk_create(objects, *args, **kwargs)


class City(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class DeliveryZone(models.Model):
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name="delivery_zones",
    )
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ("city__name", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("city", "name"), name="unique_zone_per_city"
            )
        ]

    def __str__(self) -> str:
        return f"{self.city.name}: {self.name}"


class Order(models.Model):
    objects = OrderQuerySet.as_manager()

    class State(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FUNDED = "FUNDED", "Funded"
        ACCEPTED = "ACCEPTED", "Accepted"
        PACKED = "PACKED", "Packed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        DISPUTED = "DISPUTED", "Disputed"
        FINALIZED = "FINALIZED", "Finalized"
        SETTLEMENT_PENDING = "SETTLEMENT_PENDING", "Settlement pending multisig"
        REFUNDED = "REFUNDED", "Refunded"
        PARTIAL = "PARTIAL", "Partially ruled"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"

    class DeliveryLane(models.TextChoices):
        DIGITAL = "digital", "Digital"
        CITY = "city", "City"
        DOMESTIC = "domestic", "Domestic post"
        CROSS_BORDER = "cross_border", "Cross-border"

    class DeliveryType(models.TextChoices):
        PHYSICAL = "physical", "Physical"
        DIGITAL = "digital", "Digital"

    class PaymentMethod(models.TextChoices):
        LEDGER = "ledger", "Marketplace balance"
        XMR_MULTISIG = "xmr_multisig", "Monero multisig escrow"

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    vendor = models.ForeignKey(
        "catalog.VendorProfile",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    listing = models.ForeignKey(
        "catalog.Listing",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    listing_title = models.CharField(max_length=200, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.PositiveBigIntegerField(null=True, blank=True)
    total_amount = models.PositiveBigIntegerField()
    delivery_type = models.CharField(
        max_length=8,
        choices=DeliveryType.choices,
        default=DeliveryType.PHYSICAL,
    )
    payment_method = models.CharField(
        max_length=16,
        choices=PaymentMethod.choices,
        default=PaymentMethod.LEDGER,
    )
    released_amount = models.PositiveBigIntegerField(null=True, blank=True)
    state = models.CharField(
        max_length=24,
        choices=State.choices,
        default=State.DRAFT,
        db_index=True,
    )
    delivery_lane = models.CharField(
        max_length=20,
        choices=DeliveryLane.choices,
        default=DeliveryLane.DOMESTIC,
    )
    buyer_extensions = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    dispute_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    finalize_at = models.DateTimeField(null=True, blank=True)
    funded_at = models.DateTimeField(null=True, blank=True)

    delivery_zone = models.ForeignKey(
        DeliveryZone,
        on_delete=models.PROTECT,
        related_name="orders",
        null=True,
        blank=True,
    )
    courier_reference = models.CharField(max_length=160, blank=True)
    shipping_address = EncryptedTextField(blank=True, default="")
    shipping_phone = EncryptedTextField(blank=True, default="")
    pack_photo = models.ImageField(
        upload_to=pack_photo_upload_to,
        blank=True,
        validators=[validate_pack_photo_extension, validate_upload_size],
    )
    pod_token_hash = models.CharField(max_length=64, blank=True)
    pod_token_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="order_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gt=0),
                name="order_total_positive",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        state__in=(
                            "FUNDED",
                            "ACCEPTED",
                            "PACKED",
                            "DISPATCHED",
                            "DELIVERED",
                            "FINALIZED",
                            "SETTLEMENT_PENDING",
                        )
                    )
                    | (
                        models.Q(buyer__isnull=False)
                        & models.Q(vendor__isnull=False)
                        & models.Q(listing__isnull=False)
                        & models.Q(total_amount__isnull=False)
                    )
                ),
                name="funded_order_has_required_parties",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        complete_states = {
            self.State.FUNDED,
            self.State.ACCEPTED,
            self.State.PACKED,
            self.State.DISPATCHED,
            self.State.DELIVERED,
            self.State.FINALIZED,
            self.State.SETTLEMENT_PENDING,
        }
        if self.state in complete_states and any(
            value is None
            for value in (
                self.buyer_id,
                self.vendor_id,
                self.listing_id,
                self.total_amount,
            )
        ):
            raise ValidationError(
                "Orders in this state require a buyer, vendor, listing, and total."
            )

    def save(self, *args, **kwargs) -> None:
        if self._state.adding:
            _ensure_new_orders_enabled()
            if self.expires_at is None:
                self.expires_at = timezone.now() + timedelta(minutes=30)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Order {self.pk}"


class StaffOrderTransitionQuerySet(models.QuerySet):
    def update(self, **kwargs: object) -> int:
        raise ValidationError("Staff order transition logs are immutable.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError("Staff order transition logs are immutable.")


class StaffOrderTransition(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="staff_transition_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="staff_order_transitions",
    )
    from_state = models.CharField(max_length=24, choices=Order.State.choices)
    to_state = models.CharField(max_length=24, choices=Order.State.choices)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = StaffOrderTransitionQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("order", "created_at"),
                name="orders_stf_ord_created_idx",
            )
        ]

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValidationError("Staff order transition logs are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Staff order transition logs are immutable.")


class Dispute(models.Model):
    class EvidenceKind(models.TextChoices):
        BUYER_PAYMENT = "buyer_payment", "Buyer payment"
        VENDOR_STATEMENT = "vendor_statement", "Vendor statement"
        DELIVERY = "delivery", "Delivery"
        OTHER = "other", "Other"

    order = models.OneToOneField(
        Order,
        on_delete=models.PROTECT,
        related_name="dispute",
    )
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="filed_disputes",
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Dispute for order {self.order_id}"


class DisputeEvidence(models.Model):
    dispute = models.ForeignKey(
        Dispute,
        on_delete=models.PROTECT,
        related_name="evidence",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_dispute_evidence",
    )
    kind = models.CharField(max_length=32, choices=Dispute.EvidenceKind.choices)
    description = models.CharField(max_length=500, blank=True)
    attachment = models.FileField(
        upload_to=evidence_upload_to,
        validators=[validate_evidence_extension, validate_upload_size],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.get_kind_display()} evidence for dispute {self.dispute_id}"


class PublicRuling(models.Model):
    class Outcome(models.TextChoices):
        RELEASE = "release", "Release to vendor"
        REFUND = "refund", "Refund buyer"
        PARTIAL = "partial", "Partial release"

    dispute = models.OneToOneField(
        Dispute,
        on_delete=models.PROTECT,
        related_name="public_ruling",
    )
    amount_band = models.CharField(max_length=80)
    category = models.ForeignKey(
        "catalog.Category",
        on_delete=models.PROTECT,
        related_name="public_rulings",
    )
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    reason = models.TextField(max_length=2000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValidationError("Public rulings are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        raise ValidationError("Public rulings are immutable.")

    def __str__(self) -> str:
        return f"Public ruling {self.pk}"
