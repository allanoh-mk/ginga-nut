from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import transaction
from django.utils import timezone

from core.models import FinancialJob
from core.services import outbox


class _FakeRedis:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, float]]] = []

    def zadd(self, key: str, values: dict[str, float]) -> int:
        self.added.append((key, values))
        return len(values)

    def close(self) -> None:
        pass


@pytest.mark.django_db(transaction=True)
def test_withdrawal_job_is_enqueued_only_after_transaction_commit() -> None:
    redis = _FakeRedis()
    with patch.object(outbox.Redis, "from_url", return_value=redis):
        with transaction.atomic():
            job = outbox.publish_on_commit("withdrawal", {"withdrawal_id": 17})
            assert FinancialJob.objects.filter(pk=job.pk).exists()
            assert redis.added == []

        assert redis.added == [
            (
                outbox.FINANCIAL_JOB_QUEUE,
                {str(job.pk): pytest.approx(timezone.now().timestamp(), abs=2)},
            )
        ]


@pytest.mark.django_db(transaction=True)
def test_stale_outbox_claim_is_retried_after_worker_crash() -> None:
    redis = _FakeRedis()
    job = FinancialJob.objects.create(
        job_type="withdrawal",
        payload={"withdrawal_id": 21},
        claimed_at=timezone.now() - outbox.FINANCIAL_JOB_LEASE - timedelta(seconds=1),
    )
    with patch.object(outbox.Redis, "from_url", return_value=redis):
        count = outbox.claim_pending_financial_jobs()

    assert count == 1
    assert redis.added == [
        (
            outbox.FINANCIAL_JOB_QUEUE,
            {str(job.pk): pytest.approx(timezone.now().timestamp(), abs=2)},
        )
    ]
    job.refresh_from_db()
    assert job.claimed_at > timezone.now() - outbox.FINANCIAL_JOB_LEASE
