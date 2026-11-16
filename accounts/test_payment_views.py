from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from ledger.models import Account, LedgerEntry
from payments.models import (
    Chain,
    Deposit,
    DepositAddress,
    PayoutAddress,
    Withdrawal,
)


@pytest.mark.django_db
def test_user_can_request_deposit_address_and_view_deposit_history(client) -> None:
    user = User.objects.create_user(
        username="deposit-page-user",
        password="a-very-long-unique-password-8492",
    )
    client.force_login(user)
    address = DepositAddress.objects.create(
        user=user,
        chain=Chain.TRC20,
        address="TDepositAddress",
    )

    with patch("accounts.views.create_deposit_address", return_value=address) as create:
        response = client.post(
            reverse("accounts:deposit_address_create"),
            {"chain": Chain.TRC20},
        )

    assert response.status_code == 302
    assert response.url == reverse("accounts:deposits")
    create.assert_called_once_with(user, Chain.TRC20)
    page = client.get(reverse("accounts:deposits"))
    assert page.status_code == 200
    assert b"TDepositAddress" in page.content

    Deposit.objects.create(
        address=address,
        transaction_id="history-tx",
        amount_atomic=100,
        confirmations=3,
        state=Deposit.State.CONFIRMED,
    )
    history = client.get(reverse("accounts:deposit_history"))
    assert history.status_code == 200
    assert b"history-tx" in history.content
    assert b"100 atomic units" in history.content
    assert b"Confirmed" in history.content


@pytest.mark.django_db
def test_user_withdrawal_charges_three_percent_and_shows_status(client) -> None:
    user = User.objects.create_user(
        username="withdrawal-page-user",
        password="a-very-long-unique-password-8492",
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
    LedgerEntry.objects.create(account=available, amount=1000, ref="user-funding")
    LedgerEntry.objects.create(account=external, amount=-1000, ref="user-funding")
    client.force_login(user)

    with (
        patch("core.services.request_withdrawal.publish_on_commit"),
        patch("core.services.request_withdrawal.get_chain_provider") as get_provider,
    ):
        get_provider.return_value.supports_withdrawals = True
        response = client.post(
            reverse("accounts:withdrawals"),
            {
                "payout_address": payout.pk,
                "amount": 500,
                "idempotency_key": "withdrawal-form-key",
            },
        )

    withdrawal = Withdrawal.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse(
        "accounts:withdrawal_detail",
        args=(withdrawal.pk,),
    )
    assert withdrawal.amount_base_units == 500
    assert withdrawal.fee_base_units == 15
    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"485 base units" in detail.content

    invalid = client.post(
        reverse("accounts:withdrawals"),
        {
            "payout_address": payout.pk,
            "amount": 1001,
            "idempotency_key": "too-large",
        },
    )
    assert invalid.status_code == 400
    assert Withdrawal.objects.count() == 1
