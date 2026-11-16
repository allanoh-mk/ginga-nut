from datetime import timedelta
from functools import partial
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from redis import Redis

from core.jobs import FINANCIAL_JOB_QUEUE
from core.models import FinancialJob

FINANCIAL_JOB_LEASE = timedelta(minutes=5)


def _enqueue_claimed_jobs(job_ids: list[int]) -> None:
    for job_id in job_ids:
        _enqueue_financial_job(job_id)


def _enqueue_financial_job(job_id: int) -> None:
    client = Redis.from_url(settings.QUEUE_REDIS_URL, decode_responses=True)
    try:
        client.zadd(
            FINANCIAL_JOB_QUEUE,
            {str(job_id): timezone.now().timestamp()},
        )
    finally:
        client.close()


def publish_on_commit(job_type: str, payload: dict[str, Any]) -> FinancialJob:
    job = FinancialJob.objects.create(job_type=job_type, payload=payload)
    transaction.on_commit(partial(_enqueue_financial_job, job.pk))
    return job


def claim_pending_financial_jobs(limit: int = 100) -> int:
    if limit <= 0:
        raise ValueError("Financial job claim limit must be positive.")
    now = timezone.now()
    stale_before = now - FINANCIAL_JOB_LEASE
    with transaction.atomic():
        jobs = list(
            FinancialJob.objects.select_for_update(skip_locked=True)
            .filter(completed_at__isnull=True)
            .filter(Q(claimed_at__isnull=True) | Q(claimed_at__lt=stale_before))
            .order_by("created_at", "pk")[:limit]
        )
        for job in jobs:
            job.claimed_at = now
            job.save(update_fields=("claimed_at",))
        if jobs:
            job_ids = [job.pk for job in jobs]
            transaction.on_commit(partial(_enqueue_claimed_jobs, job_ids))
    return len(jobs)
