from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, close_old_connections, connections, transaction

from core.services.post_transfer import post_transfer
from core.services.reconcile_ledger import reconcile_ledger
from ledger.exceptions import InsufficientFunds, LedgerImbalance
from ledger.models import Account, LedgerEntry


@pytest.mark.django_db
def test_post_transfer_writes_a_balanced_pair() -> None:
    source = Account.objects.create(kind=Account.Kind.USER_AVAILABLE)
    destination = Account.objects.create(kind=Account.Kind.USER_ESCROW)
    treasury = Account.objects.create(kind=Account.Kind.TREASURY)
    LedgerEntry.objects.create(account=source, amount=1_000, ref="opening")
    LedgerEntry.objects.create(account=treasury, amount=-1_000, ref="opening")

    debit, credit = post_transfer(source, destination, 350, "order-17")

    assert debit.account_id == source.pk
    assert debit.amount == -350
    assert credit.account_id == destination.pk
    assert credit.amount == 350
    assert debit.ref == credit.ref == "order-17"
    assert debit.order_id is credit.order_id is None
    assert Account.objects.get(pk=source.pk).balance == 650
    assert Account.objects.get(pk=destination.pk).balance == 350
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_post_transfer_rejects_insufficient_funds_without_writing() -> None:
    source = Account.objects.create(kind=Account.Kind.USER_AVAILABLE)
    destination = Account.objects.create(kind=Account.Kind.USER_ESCROW)
    LedgerEntry.objects.create(account=source, amount=10, ref="opening")
    before = LedgerEntry.objects.count()

    with pytest.raises(InsufficientFunds):
        post_transfer(source, destination, 11, "order-18")

    assert LedgerEntry.objects.count() == before


@pytest.mark.django_db(transaction=True)
def test_concurrent_transfers_cannot_overspend_the_same_account() -> None:
    if connections["default"].vendor != "postgresql":
        pytest.skip("select_for_update concurrency requires PostgreSQL.")

    source = Account.objects.create(kind=Account.Kind.USER_AVAILABLE)
    first_destination = Account.objects.create(kind=Account.Kind.USER_ESCROW)
    second_destination = Account.objects.create(kind=Account.Kind.USER_ESCROW)
    treasury = Account.objects.create(kind=Account.Kind.TREASURY)
    LedgerEntry.objects.create(account=source, amount=100, ref="opening")
    LedgerEntry.objects.create(account=treasury, amount=-100, ref="opening")
    barrier = Barrier(2)

    def transfer(destination_id: int, reference: str) -> str:
        close_old_connections()
        try:
            source_account = Account.objects.get(pk=source.pk)
            destination = Account.objects.get(pk=destination_id)
            barrier.wait(timeout=10)
            try:
                post_transfer(source_account, destination, 80, reference)
            except InsufficientFunds:
                return "insufficient"
            return "transferred"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda args: transfer(*args),
                [
                    (first_destination.pk, "concurrent-1"),
                    (second_destination.pk, "concurrent-2"),
                ],
            )
        )

    assert sorted(outcomes) == ["insufficient", "transferred"]
    assert Account.objects.get(pk=source.pk).balance == 20
    assert first_destination.balance + second_destination.balance == 80
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_reconcile_command_reports_a_manually_broken_pair() -> None:
    account = Account.objects.create(kind=Account.Kind.USER_AVAILABLE)
    LedgerEntry.objects.create(account=account, amount=25, ref="manual-unmatched")

    with pytest.raises(CommandError, match="global sum is 25"):
        call_command("reconcile")

    with pytest.raises(LedgerImbalance):
        reconcile_ledger()


@pytest.mark.django_db
def test_ledger_entries_cannot_be_updated_or_deleted() -> None:
    account = Account.objects.create(kind=Account.Kind.USER_AVAILABLE)
    entry = LedgerEntry.objects.create(account=account, amount=1, ref="immutable")

    with pytest.raises(ValidationError, match="immutable"):
        entry.save()
    with pytest.raises(ValidationError, match="immutable"):
        entry.delete()
    with pytest.raises(ValidationError, match="immutable"):
        LedgerEntry.objects.filter(pk=entry.pk).update(amount=2)
    with pytest.raises(ValidationError, match="immutable"):
        LedgerEntry.objects.filter(pk=entry.pk).delete()


@pytest.mark.django_db
def test_postgresql_trigger_rejects_raw_ledger_updates() -> None:
    if connections["default"].vendor != "postgresql":
        pytest.skip("The database immutability trigger is PostgreSQL-specific.")

    account = Account.objects.create(kind=Account.Kind.USER_AVAILABLE)
    entry = LedgerEntry.objects.create(account=account, amount=1, ref="immutable")

    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connections["default"].cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE ledger_ledgerentry SET amount = 2 WHERE id = %s",
            [entry.pk],
        )
