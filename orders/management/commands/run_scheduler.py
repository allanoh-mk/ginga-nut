import logging

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from core.services.expire_funding import expire_funding
from core.services.finalize import finalize
from core.services.order_deadlines import FUNDED_VENDOR_RESPONSE_LIFETIME
from orders.models import Order

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Expire stale draft/funded orders, finalize delivered orders, and purge stale rate quotes."

    def handle(self, *args, **options) -> None:
        now = timezone.now()
        expired = self._expire_drafts(now) + self._expire_funded(now)
        finalized = self._finalize_delivered(now)
        quotes_purged = self._purge_rate_quotes(now)
        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduler: expired={expired}, finalized={finalized}, quotes_purged={quotes_purged}"
            )
        )

    def _expire_drafts(self, now) -> int:
        qs = Order.objects.filter(
            state=Order.State.DRAFT,
            expires_at__lte=now,
        ).values_list("pk", flat=True)
        count = 0
        for order_id in qs:
            try:
                with transaction.atomic():
                    # Re-select with lock inside the atomic block; skip_locked
                    # ensures concurrent scheduler runs don't double-process.
                    locked = (
                        Order.objects.select_for_update(skip_locked=True)
                        .filter(pk=order_id, state=Order.State.DRAFT)
                        .first()
                    )
                    if locked is None:
                        continue
                    expire_funding(order_id, now=now)
                    count += 1
            except ValidationError as exc:
                logger.warning("expire_drafts: order %s skipped — %s", order_id, exc)
        return count

    def _expire_funded(self, now) -> int:
        deadline_cutoff = now - FUNDED_VENDOR_RESPONSE_LIFETIME
        qs = Order.objects.filter(
            state=Order.State.FUNDED,
            funded_at__lte=deadline_cutoff,
        ).values_list("pk", flat=True)
        count = 0
        for order_id in qs:
            try:
                with transaction.atomic():
                    locked = (
                        Order.objects.select_for_update(skip_locked=True)
                        .filter(pk=order_id, state=Order.State.FUNDED)
                        .first()
                    )
                    if locked is None:
                        continue
                    expire_funding(order_id, now=now)
                    count += 1
            except ValidationError as exc:
                logger.warning("expire_funded: order %s skipped — %s", order_id, exc)
        return count

    def _finalize_delivered(self, now) -> int:
        qs = Order.objects.filter(
            state=Order.State.DELIVERED,
            finalize_at__lte=now,
        ).values_list("pk", flat=True)
        count = 0
        for order_id in qs:
            try:
                with transaction.atomic():
                    locked = (
                        Order.objects.select_for_update(skip_locked=True)
                        .filter(pk=order_id, state=Order.State.DELIVERED)
                        .first()
                    )
                    if locked is None:
                        continue
                    finalize(order_id, now=now)
                    count += 1
            except ValidationError as exc:
                logger.warning(
                    "finalize_delivered: order %s skipped — %s", order_id, exc
                )
        return count

    def _purge_rate_quotes(self, now) -> int:
        # RateQuote overrides .delete() to raise ValidationError, so we bypass
        # the ORM delete and issue raw SQL directly.
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM payments_ratequote WHERE locked_until < %s AND consumed_at IS NULL",
                [now],
            )
            return cursor.rowcount
