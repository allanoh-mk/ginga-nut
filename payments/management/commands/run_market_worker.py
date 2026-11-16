import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from redis import Redis

from core.jobs import FINANCIAL_JOB_QUEUE
from core.models import FinancialJob
from core.services.is_market_feature_enabled import is_market_feature_enabled
from core.services.monero_order_escrow import process_monero_order_escrow_job
from core.services.outbox import claim_pending_financial_jobs
from core.services.process_withdrawal import process_withdrawal
from payments.models import Withdrawal

logger = logging.getLogger(__name__)
_POP_DUE_JOB = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
if #due == 0 then
    return nil
end
redis.call('ZREM', KEYS[1], due[1])
return due[1]
"""


class Command(BaseCommand):
    help = "Consume withdrawal jobs from Redis."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=1)

    def handle(self, *args, **options) -> None:
        if options["interval"] <= 0:
            raise ValueError("Worker interval must be positive.")
        client = Redis.from_url(settings.QUEUE_REDIS_URL, decode_responses=True)
        while True:
            claim_pending_financial_jobs()
            self._process_financial_jobs(client)
            if options["once"]:
                return
            time.sleep(options["interval"])

    def _process_financial_jobs(self, client: Redis) -> None:
        while True:
            job_id = client.eval(
                _POP_DUE_JOB,
                1,
                FINANCIAL_JOB_QUEUE,
                timezone.now().timestamp(),
            )
            if job_id is None:
                return
            self._run_financial_job(client, int(job_id))

    def _run_financial_job(self, client: Redis, job_id: int) -> None:
        job = FinancialJob.objects.filter(pk=job_id).first()
        if job is None or job.completed_at is not None:
            return
        try:
            if job.job_type == "withdrawal":
                if not is_market_feature_enabled("withdrawals"):
                    client.zadd(
                        FINANCIAL_JOB_QUEUE,
                        {str(job_id): timezone.now().timestamp() + 60},
                    )
                    return
                withdrawal_id = job.payload.get("withdrawal_id")
                if isinstance(withdrawal_id, bool) or not isinstance(
                    withdrawal_id, int
                ):
                    raise ValueError("Withdrawal job has an invalid withdrawal_id.")
                withdrawal = Withdrawal.objects.filter(pk=withdrawal_id).first()
                if withdrawal is None:
                    raise Withdrawal.DoesNotExist(
                        f"Withdrawal {withdrawal_id} does not exist."
                    )
                process_withdrawal(withdrawal)
            elif job.job_type in {
                "monero_escrow_create",
                "monero_escrow_settlement",
                "monero_escrow_cancel",
            }:
                escrow_id = job.payload.get("escrow_id")
                if isinstance(escrow_id, bool) or not isinstance(escrow_id, int):
                    raise ValueError("Monero escrow job has an invalid escrow_id.")
                process_monero_order_escrow_job(escrow_id)
            else:
                raise ValueError(f"Unsupported financial job type: {job.job_type}")
        except Exception as exc:
            logger.exception("Financial job %s failed and will be retried.", job_id)
            self._record_job_error(job_id, str(exc))
            client.zadd(
                FINANCIAL_JOB_QUEUE,
                {str(job_id): timezone.now().timestamp() + 60},
            )
            return
        with transaction.atomic():
            locked = FinancialJob.objects.select_for_update().get(pk=job_id)
            if locked.completed_at is None:
                locked.completed_at = timezone.now()
                locked.error = ""
                locked.save(update_fields=("completed_at", "error"))

    @staticmethod
    @transaction.atomic
    def _record_job_error(job_id: int, error: str) -> None:
        job = FinancialJob.objects.select_for_update().get(pk=job_id)
        if job.completed_at is None:
            job.error = error[:4000]
            job.save(update_fields=("error",))
