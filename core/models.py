from django.conf import settings
from django.db import models


class FinancialJob(models.Model):
    job_type = models.CharField(max_length=32)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(
                fields=("completed_at", "claimed_at", "created_at"),
                name="core_finjob_pending_idx",
            )
        ]


class Notification(models.Model):
    class Type(models.TextChoices):
        ORDER_FUNDED = "order_funded", "Order funded"
        ORDER_ACCEPTED = "order_accepted", "Order accepted"
        ORDER_REJECTED = "order_rejected", "Order rejected"
        ORDER_PACKED = "order_packed", "Order packed"
        ORDER_DISPATCHED = "order_dispatched", "Order dispatched"
        ORDER_DELIVERED = "order_delivered", "Order delivered"
        ORDER_FINALIZED = "order_finalized", "Order finalized"
        ORDER_CANCELLED = "order_cancelled", "Order cancelled"
        ORDER_EXPIRED = "order_expired", "Order expired"
        ORDER_REFUNDED = "order_refunded", "Order refunded"
        SETTLEMENT_PENDING = "settlement_pending", "Settlement pending"
        SETTLEMENT_COMPLETED = "settlement_completed", "Settlement completed"
        DISPUTE_OPENED = "dispute_opened", "Dispute opened"
        DISPUTE_RULING = "dispute_ruling", "Dispute ruling"
        WITHDRAWAL_APPROVED = "withdrawal_approved", "Withdrawal approved"
        WITHDRAWAL_SENT = "withdrawal_sent", "Withdrawal sent"
        VENDOR_APPROVED = "vendor_approved", "Vendor approved"
        LISTING_APPROVED = "listing_approved", "Listing approved"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="notifications_sent",
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    message = models.CharField(max_length=255)
    data = models.JSONField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("recipient", "read_at"),
                name="core_notification_rec_read_idx",
            )
        ]
