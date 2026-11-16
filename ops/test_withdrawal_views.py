from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.services.request_withdrawal import request_withdrawal
from ledger.models import Account, LedgerEntry
from payments.models import Chain, PayoutAddress, Withdrawal


@pytest.mark.django_db
def test_staff_can_review_over_cap_withdrawals(client, settings) -> None:
    settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = 10
    user = User.objects.create_user(
        username="manual-withdrawal-user",
        password="a-very-long-unique-password-8492",
    )
    staff = User.objects.create_user(
        username="withdrawal-reviewer",
        password="a-very-long-unique-password-8493",
        is_staff=True,
    )
    payout = PayoutAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address="1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        label="Verified",
        available_after=timezone.now() - timedelta(days=1),
        verified_at=timezone.now(),
    )
    available = Account.objects.create(
        kind=Account.Kind.USER_AVAILABLE,
        owner=user,
    )
    external, _ = Account.objects.get_or_create(
        kind=Account.Kind.EXTERNAL,
        owner=None,
    )
    LedgerEntry.objects.create(account=available, amount=1000, ref="review-funding")
    LedgerEntry.objects.create(account=external, amount=-1000, ref="review-funding")

    with (
        patch("core.services.request_withdrawal.publish_on_commit"),
        patch("core.services.request_withdrawal.get_chain_provider") as get_provider,
    ):
        get_provider.return_value.supports_withdrawals = True
        first = request_withdrawal(
            user,
            Chain.BTC,
            payout.address,
            100,
            "review-approved",
        )
        second = request_withdrawal(
            user,
            Chain.BTC,
            payout.address,
            100,
            "review-rejected",
        )

    assert first.state == Withdrawal.State.MANUAL_APPROVAL
    assert second.state == Withdrawal.State.MANUAL_APPROVAL
    client.force_login(staff)
    queue_url = reverse("ops:withdrawal-approval-queue")
    response = client.get(queue_url)
    assert response.status_code == 200
    assert b"Pending withdrawal approvals" in response.content

    with patch("core.services.approve_withdrawal.publish_on_commit") as publish:
        approved = client.post(
            reverse("ops:withdrawal-approve", args=(first.pk,)),
        )
    assert approved.status_code == 302
    first.refresh_from_db()
    assert first.state == Withdrawal.State.APPROVED
    publish.assert_called_once_with("withdrawal", {"withdrawal_id": first.pk})

    rejected = client.post(
        reverse("ops:withdrawal-reject", args=(second.pk,)),
        {"reason": "Please verify your payout details."},
    )
    assert rejected.status_code == 302
    second.refresh_from_db()
    assert second.state == Withdrawal.State.REJECTED
    assert second.rejection_reason == "Please verify your payout details."
    assert available.balance == 900
    assert (
        Account.objects.get(
            kind=Account.Kind.USER_ESCROW,
            owner=user,
        ).balance
        == 100
    )
    client.force_login(user)
    detail = client.get(
        reverse("accounts:withdrawal_detail", args=(second.pk,)),
    )
    assert detail.status_code == 200
    assert b"Not charged" in detail.content
    assert b"100 base units" in detail.content
