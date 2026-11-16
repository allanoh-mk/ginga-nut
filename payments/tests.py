from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.core.management import call_command
from django.utils import timezone
from tronpy.keys import PrivateKey

from accounts.models import User
from catalog.models import VendorProfile
from core.services.approve_withdrawal import approve_withdrawal
from core.services.capture_rate_feed import capture_rate_feed
from core.services.convert_deposit import convert_deposit
from core.services.create_deposit_address import create_deposit_address
from core.services.create_payout_address_challenge import (
    create_payout_address_challenge,
)
from core.services.create_wallet_link_challenge import create_wallet_link_challenge
from core.services.delete_payout_address import delete_payout_address
from core.services.fake_deposit import fake_deposit
from core.services.issue_rate_quote import RateDivergence, issue_rate_quote
from core.services.orphan_unseen_deposits import orphan_unseen_deposits
from core.services.poll_deposits import poll_deposits
from core.services.process_withdrawal import process_withdrawal
from core.services.promote_deposit import promote_deposit
from core.services.reconcile_ledger import reconcile_ledger
from core.services.record_deposit_transfer import record_deposit_transfer
from core.services.reject_withdrawal import reject_withdrawal
from core.services.request_withdrawal import request_withdrawal
from core.services.reverse_deposit import reverse_deposit
from core.services.save_payout_address import save_payout_address
from core.services.set_market_feature import set_market_feature
from core.services.sweep_market_fees import sweep_market_fees
from core.services.sweep_monero_deposits import sweep_monero_deposits
from core.services.unlink_wallet import unlink_wallet
from core.services.verify_payout_address_challenge import (
    verify_payout_address_challenge,
)
from core.services.verify_wallet_link_challenge import verify_wallet_link_challenge
from core.services.watch_chain import watch_chain
from ledger.exceptions import InsufficientFunds
from ledger.models import Account, LedgerEntry
from payments.models import (
    Chain,
    ChainPollWatermark,
    Deposit,
    DepositAddress,
    DepositEvent,
    PayoutAddress,
    RateQuote,
    RateTick,
    WalletLink,
    Withdrawal,
)
from payments.providers.base import (
    ChainTransfer,
    ProviderError,
)
from payments.providers.btcpay import BTCPayProvider
from payments.providers.fake import FakeProvider
from payments.providers.monero import MoneroWalletProvider
from payments.providers.rates import RateSample
from payments.providers.trongrid import TronGridProvider

TEST_BTC_ADDRESS = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
TEST_OTHER_BTC_ADDRESS = "1BitcoinEaterAddressDontSendf59kuE"


def _create_ready_payout(user, address: str = TEST_BTC_ADDRESS) -> PayoutAddress:
    return PayoutAddress.objects.create(
        user=user,
        chain=Chain.BTC,
        address=address,
        label="Test payout",
        available_after=timezone.now() - timedelta(days=1),
        verified_at=timezone.now(),
    )


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(username="payments-user", password="long-password")


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_superuser(
        username="payments-admin",
        password="long-password",
    )


def create_quote(user, chain=Chain.BTC, amount=100_000_000, rate=100_000_000, **kwargs):
    now = timezone.now()
    tick_a = RateTick.objects.create(
        chain=chain, source="a", base_units_per_coin=rate, observed_at=now
    )
    tick_b = RateTick.objects.create(
        chain=chain, source="b", base_units_per_coin=rate, observed_at=now
    )
    return RateQuote.objects.create(
        user=user,
        chain=chain,
        source_a=tick_a,
        source_b=tick_b,
        base_units_per_coin=rate,
        amount_min_atomic=amount,
        amount_max_atomic=amount,
        locked_until=kwargs.get("locked_until", now + timedelta(minutes=10)),
    )


def _tron_test_key(seed: str = "11") -> PrivateKey:
    return PrivateKey(bytes.fromhex(seed * 32))


def _sign_wallet_challenge(challenge, key: PrivateKey) -> str:
    return key.sign_msg(challenge.message_to_sign.encode("utf-8")).hex()


@pytest.mark.django_db
def test_wallet_link_signature_proves_tron_address_and_is_single_use(user) -> None:
    key = _tron_test_key()
    address = key.public_key.to_base58check_address()
    challenge = create_wallet_link_challenge(user, WalletLink.Chain.TRC20, address)

    wallet_link = verify_wallet_link_challenge(
        user,
        challenge.pk,
        _sign_wallet_challenge(challenge, key),
    )

    assert wallet_link.user == user
    assert wallet_link.address == address
    assert wallet_link.unlinked_at is None
    challenge.refresh_from_db()
    assert challenge.consumed_at is not None
    with pytest.raises(ValidationError, match="expired or already used"):
        verify_wallet_link_challenge(
            user,
            challenge.pk,
            _sign_wallet_challenge(challenge, key),
        )


@pytest.mark.django_db
def test_wallet_link_rejects_mismatched_signer_and_locks_after_five_attempts(
    user,
) -> None:
    challenge_key = _tron_test_key()
    wrong_key = _tron_test_key("22")
    challenge = create_wallet_link_challenge(
        user,
        WalletLink.Chain.TRC20,
        challenge_key.public_key.to_base58check_address(),
    )
    signature = _sign_wallet_challenge(challenge, wrong_key)

    for attempt in range(5):
        with pytest.raises(ValidationError, match="does not match"):
            verify_wallet_link_challenge(user, challenge.pk, signature)
        challenge.refresh_from_db()
        assert challenge.attempts == attempt + 1

    assert challenge.consumed_at is not None
    assert not WalletLink.objects.filter(user=user).exists()
    with pytest.raises(ValidationError, match="expired or already used"):
        verify_wallet_link_challenge(
            user,
            challenge.pk,
            _sign_wallet_challenge(challenge, challenge_key),
        )


@pytest.mark.django_db
def test_wallet_link_challenge_rejects_bad_addresses_and_expired_signatures(
    user,
) -> None:
    with pytest.raises(ValidationError, match="valid TRON address"):
        create_wallet_link_challenge(user, WalletLink.Chain.TRC20, "not-an-address")
    with pytest.raises(ValidationError, match="supported for TRON only"):
        create_wallet_link_challenge(user, Chain.BTC, "not-an-address")

    key = _tron_test_key()
    challenge = create_wallet_link_challenge(
        user,
        WalletLink.Chain.TRC20,
        key.public_key.to_base58check_address(),
    )
    challenge.expires_at = timezone.now() - timedelta(seconds=1)
    challenge.save(update_fields=("expires_at",))

    with pytest.raises(ValidationError, match="expired or already used"):
        verify_wallet_link_challenge(
            user,
            challenge.pk,
            _sign_wallet_challenge(challenge, key),
        )
    assert not WalletLink.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_one_wallet_address_cannot_be_linked_to_two_accounts(user) -> None:
    other_user = User.objects.create_user(username="other-wallet-user")
    key = _tron_test_key()
    address = key.public_key.to_base58check_address()
    first_challenge = create_wallet_link_challenge(
        user,
        WalletLink.Chain.TRC20,
        address,
    )
    first_link = verify_wallet_link_challenge(
        user,
        first_challenge.pk,
        _sign_wallet_challenge(first_challenge, key),
    )
    second_challenge = create_wallet_link_challenge(
        other_user,
        WalletLink.Chain.TRC20,
        address,
    )

    with pytest.raises(ValidationError, match="already linked to another account"):
        verify_wallet_link_challenge(
            other_user,
            second_challenge.pk,
            _sign_wallet_challenge(second_challenge, key),
        )

    first_link.refresh_from_db()
    second_challenge.refresh_from_db()
    assert first_link.user == user
    assert first_link.unlinked_at is None
    assert second_challenge.consumed_at is not None
    assert (
        WalletLink.objects.filter(
            chain=WalletLink.Chain.TRC20,
            address=address,
            unlinked_at__isnull=True,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_wallets_can_be_unlinked_without_erasing_link_history(user) -> None:
    keys = (_tron_test_key(), _tron_test_key("22"))
    links = []
    for key in keys:
        challenge = create_wallet_link_challenge(
            user,
            WalletLink.Chain.TRC20,
            key.public_key.to_base58check_address(),
        )
        links.append(
            verify_wallet_link_challenge(
                user,
                challenge.pk,
                _sign_wallet_challenge(challenge, key),
            )
        )

    unlink_wallet(user, links[0].pk)

    links[0].refresh_from_db()
    assert links[0].unlinked_at is not None
    assert (
        WalletLink.objects.filter(
            user=user,
            unlinked_at__isnull=True,
        ).count()
        == 1
    )
    assert WalletLink.objects.filter(user=user).count() == 2


@pytest.mark.django_db
def test_payout_address_requires_matching_addresses_and_valid_checksum(user) -> None:
    with pytest.raises(ValidationError, match="do not match"):
        save_payout_address(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            TEST_OTHER_BTC_ADDRESS,
            "Cold wallet",
        )
    with pytest.raises(ValidationError, match="Invalid BTC payout address"):
        save_payout_address(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS[:-1] + "1",
            TEST_BTC_ADDRESS[:-1] + "1",
            "Bad checksum",
        )
    payout = save_payout_address(
        user,
        Chain.BTC,
        TEST_BTC_ADDRESS,
        TEST_BTC_ADDRESS,
        "Cold wallet",
    )
    assert payout.label == "Cold wallet"
    assert payout.address == TEST_BTC_ADDRESS
    assert payout.available_after > timezone.now() + timedelta(hours=23)


@pytest.mark.django_db
def test_segwit_payout_address_validates_witness_checksum_and_prefix(user) -> None:
    address = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

    payout = save_payout_address(
        user,
        Chain.BTC,
        address,
        address,
        "SegWit",
    )

    assert payout.address == address
    with pytest.raises(ValidationError, match="Invalid BTC payout address"):
        save_payout_address(
            user,
            Chain.BTC,
            address[:-1] + "a",
            address[:-1] + "a",
            "Bad SegWit",
        )


@pytest.mark.django_db
def test_payout_address_optional_verification_requires_valid_tron_signature(
    user,
) -> None:
    key = _tron_test_key("44")
    payout = save_payout_address(
        user,
        Chain.TRC20,
        key.public_key.to_base58check_address(),
        key.public_key.to_base58check_address(),
        "TRON cold wallet",
    )
    challenge = create_payout_address_challenge(user, payout.pk)
    wrong_signature = _sign_wallet_challenge(challenge, _tron_test_key("55"))

    with pytest.raises(ValidationError, match="does not match"):
        verify_payout_address_challenge(user, challenge.pk, wrong_signature)
    payout.refresh_from_db()
    assert payout.verified_at is None

    challenge = create_payout_address_challenge(user, payout.pk)
    valid_signature = key.sign_msg(challenge.message_to_sign.encode()).hex()
    verify_payout_address_challenge(user, challenge.pk, valid_signature)

    payout.refresh_from_db()
    assert payout.verified_at is not None
    with pytest.raises(ValidationError, match="expired or used"):
        verify_payout_address_challenge(user, challenge.pk, valid_signature)


@pytest.mark.django_db
def test_fresh_payout_address_is_locked_out_of_withdrawals(user) -> None:
    save_payout_address(
        user,
        Chain.BTC,
        TEST_BTC_ADDRESS,
        TEST_BTC_ADDRESS,
        "New address",
    )

    payout = PayoutAddress.objects.get(user=user, chain=Chain.BTC)
    payout.verified_at = timezone.now()
    payout.save(update_fields=("verified_at",))
    with pytest.raises(ValidationError, match="locked for 24 hours"):
        request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            1,
            "fresh-address",
        )


@pytest.mark.django_db
def test_deleted_payout_address_is_retained_and_cannot_be_reused(user) -> None:
    payout = save_payout_address(
        user,
        Chain.BTC,
        TEST_BTC_ADDRESS,
        TEST_BTC_ADDRESS,
        "Old address",
    )

    delete_payout_address(user, payout.pk)

    payout.refresh_from_db()
    assert payout.deleted_at is not None
    replacement = save_payout_address(
        user,
        Chain.BTC,
        TEST_BTC_ADDRESS,
        TEST_BTC_ADDRESS,
        "Replacement",
    )
    assert replacement.pk != payout.pk


@pytest.mark.django_db
def test_create_deposit_address_is_reused_per_user_and_chain(user) -> None:
    first = create_deposit_address(user, Chain.BTC)
    second = create_deposit_address(user, Chain.BTC)
    other_chain = create_deposit_address(user, Chain.LTC)

    assert first.pk == second.pk
    assert first.address == second.address
    assert other_chain.pk != first.pk


@pytest.mark.django_db
def test_create_deposit_address_rejects_provider_without_deposit_support(user) -> None:
    provider = MagicMock(supports_deposit=False)
    with (
        patch(
            "core.services.create_deposit_address.get_chain_provider",
            return_value=provider,
        ),
        pytest.raises(ValidationError, match="does not support deposits"),
    ):
        create_deposit_address(user, Chain.BTC)

    provider.new_address.assert_not_called()
    assert not DepositAddress.objects.filter(user=user, chain=Chain.BTC).exists()


@pytest.mark.django_db
def test_fake_deposit_runs_through_confirmation_conversion_and_is_idempotent(
    user,
) -> None:
    first = fake_deposit(
        user,
        Chain.BTC,
        "fake-e2e",
        100_000_000,
        100_000_000,
        2,
    )
    before = LedgerEntry.objects.count()

    repeated = fake_deposit(
        user,
        Chain.BTC,
        "fake-e2e",
        100_000_000,
        100_000_000,
        2,
    )

    assert first.state == Deposit.State.CREDITED
    assert repeated.pk == first.pk
    assert LedgerEntry.objects.count() == before
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_fake_deposit_management_command_credits_without_network(user) -> None:
    output = StringIO()

    call_command(
        "fake_deposit",
        user.username,
        Chain.BTC,
        "fake-command-tx",
        100_000_000,
        100_000_000,
        stdout=output,
    )

    deposit = Deposit.objects.get(transaction_id="fake-command-tx")
    assert deposit.state == Deposit.State.CREDITED
    assert "credited" in output.getvalue()
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_provider_credit_waits_for_configured_confirmation_depth(
    user, settings
) -> None:
    settings.MARKET_CHAIN_CONFIRMATIONS = {
        **settings.MARKET_CHAIN_CONFIRMATIONS,
        "BTC": 3,
    }
    address = create_deposit_address(user, Chain.BTC)
    provider = FakeProvider(Chain.BTC)
    transfer = ChainTransfer("tx-confirming", address.address, 100_000_000, 2)

    deposit = record_deposit_transfer(Chain.BTC, transfer, provider)
    assert deposit.state == Deposit.State.SEEN
    deposit = promote_deposit(deposit)
    assert deposit.state == Deposit.State.CONFIRMING

    updated = record_deposit_transfer(
        Chain.BTC,
        ChainTransfer("tx-confirming", address.address, 100_000_000, 3),
        provider,
    )
    updated = promote_deposit(updated)
    assert updated.pk == deposit.pk
    assert updated.state == Deposit.State.CONFIRMED


@pytest.mark.django_db
def test_unknown_tron_contract_stays_seen_and_blacklist_holds_promotion(
    user,
    settings,
) -> None:
    settings.TRC20_CONTRACT_WHITELIST = ["trusted-contract"]
    settings.MARKET_CHAIN_CONFIRMATIONS = {
        **settings.MARKET_CHAIN_CONFIRMATIONS,
        Chain.TRC20: 1,
    }
    address = create_deposit_address(user, Chain.TRC20)
    provider = FakeProvider(Chain.TRC20)

    unknown = record_deposit_transfer(
        Chain.TRC20,
        ChainTransfer(
            "unknown-token",
            address.address,
            100,
            10,
            contract_address="unrecognized-contract",
        ),
        provider,
    )
    assert unknown.state == Deposit.State.SEEN

    blacklisted = record_deposit_transfer(
        Chain.TRC20,
        ChainTransfer(
            "blacklisted-token",
            address.address,
            100,
            10,
            contract_address="trusted-contract",
            sender="Tsender",
            recipient=address.address,
            blacklisted=True,
        ),
        provider,
    )
    blacklisted = promote_deposit(blacklisted)
    assert blacklisted.state == Deposit.State.CONFIRMING
    assert blacklisted.blacklisted


@pytest.mark.django_db
def test_depth_drop_after_credit_reverses_spendable_amount_and_books_shortfall(
    user,
    settings,
) -> None:
    settings.MARKET_CHAIN_CONFIRMATIONS = {
        **settings.MARKET_CHAIN_CONFIRMATIONS,
        Chain.BTC: 2,
    }
    address = create_deposit_address(user, Chain.BTC)
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="credited-then-reorged",
        amount_atomic=100,
        confirmations=2,
        state=Deposit.State.CREDITED,
        base_amount=100,
        credited_at=timezone.now(),
    )
    available = Account.objects.create(
        kind=Account.Kind.USER_AVAILABLE,
        owner=user,
    )
    external = Account.objects.get(
        kind=Account.Kind.EXTERNAL,
        owner__isnull=True,
    )
    LedgerEntry.objects.create(account=available, amount=100, ref="original-credit")
    LedgerEntry.objects.create(account=external, amount=-100, ref="original-credit")
    LedgerEntry.objects.create(account=available, amount=-70, ref="user-spend")
    LedgerEntry.objects.create(account=external, amount=70, ref="user-spend")
    provider = FakeProvider(Chain.BTC)

    reversed_deposit = record_deposit_transfer(
        Chain.BTC,
        ChainTransfer("credited-then-reorged", address.address, 100, 1),
        provider,
    )

    available.refresh_from_db()
    suspense = Account.objects.get(
        kind=Account.Kind.SUSPENSE,
        owner__isnull=True,
    )
    assert reversed_deposit.state == Deposit.State.REVERSED
    assert available.balance == 0
    assert suspense.balance == -70
    assert DepositEvent.objects.filter(
        deposit=deposit,
        to_state=Deposit.State.REVERSED,
        reason="depth_drop",
    ).exists()
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_replaced_one_confirmation_deposit_is_reversed_when_snapshot_drops_txid(
    user,
) -> None:
    address = create_deposit_address(user, Chain.XMR)
    old_tx = Deposit.objects.create(
        address=address,
        transaction_id="old-rbf-txid",
        amount_atomic=100,
        confirmations=1,
        state=Deposit.State.CREDITED,
        base_amount=100,
    )
    available = Account.objects.create(
        kind=Account.Kind.USER_AVAILABLE,
        owner=user,
    )
    external = Account.objects.get(
        kind=Account.Kind.EXTERNAL,
        owner__isnull=True,
    )
    LedgerEntry.objects.create(account=available, amount=100, ref="old-tx-credit")
    LedgerEntry.objects.create(account=external, amount=-100, ref="old-tx-credit")
    replacement_tx = Deposit.objects.create(
        address=address,
        transaction_id="replacement-txid",
        amount_atomic=100,
        confirmations=1,
        state=Deposit.State.CONFIRMING,
    )

    orphaned = orphan_unseen_deposits(
        Chain.XMR,
        {(address.address, replacement_tx.transaction_id, "")},
    )

    assert old_tx.pk in {deposit.pk for deposit in orphaned}
    old_tx.refresh_from_db()
    replacement_tx.refresh_from_db()
    assert old_tx.state == Deposit.State.REVERSED
    assert replacement_tx.state == Deposit.State.CONFIRMING
    assert available.balance == 0
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_poll_deposits_records_provider_transfers(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    provider = FakeProvider(Chain.BTC)
    provider.add_transfer(ChainTransfer("tx-polled", address.address, 100_000_000, 2))
    with patch("core.services.poll_deposits.get_chain_provider", return_value=provider):
        deposits = poll_deposits(Chain.BTC)

    assert len(deposits) == 1
    assert deposits[0].transaction_id == "tx-polled"
    assert deposits[0].state == Deposit.State.CONFIRMED


@pytest.mark.django_db
def test_chain_watcher_refreshes_rates_and_leaves_conversion_for_user(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    provider = FakeProvider(Chain.BTC)
    provider.add_transfer(ChainTransfer("tx-watcher", address.address, 100_000_000, 2))
    now = timezone.now()
    samples = (
        RateSample("coinbase", 100_000_000, now),
        RateSample("kraken", 100_000_000, now),
    )
    with (
        patch(
            "core.services.capture_rate_feed.fetch_rate_samples",
            return_value=samples,
        ),
        patch(
            "core.services.poll_deposits.get_chain_provider",
            return_value=provider,
        ),
    ):
        watch_chain(Chain.BTC)

    deposit = Deposit.objects.get(transaction_id="tx-watcher")
    assert deposit.state == Deposit.State.CONFIRMED
    assert deposit.quote is None
    assert deposit.conversion_processed_at is None
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_deposit_conversion_posts_three_percent_fee_and_balances_ledger(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="tx-convert",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    quote = create_quote(user)

    converted = convert_deposit(deposit, quote)

    available = Account.objects.get(
        kind=Account.Kind.USER_AVAILABLE,
        owner=user,
    )
    market_fee = Account.objects.get(kind=Account.Kind.MARKET_FEE, owner__isnull=True)
    assert converted.state == Deposit.State.CREDITED
    assert converted.base_amount == 97_000_000
    assert available.balance == 97_000_000
    assert market_fee.balance == 3_000_000
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_reversing_deposit_refunds_commission_after_fee_sweep(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="tx-reverse-after-sweep",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    converted = convert_deposit(deposit, create_quote(user))
    assert sweep_market_fees() == 3_000_000

    reversed_deposit = reverse_deposit(converted, "depth_drop")

    available = Account.objects.get(
        kind=Account.Kind.USER_AVAILABLE,
        owner=user,
    )
    market_fee = Account.objects.get(kind=Account.Kind.MARKET_FEE, owner__isnull=True)
    treasury = Account.objects.get(kind=Account.Kind.TREASURY, owner__isnull=True)
    assert reversed_deposit.state == Deposit.State.REVERSED
    assert available.balance == 0
    assert market_fee.balance == 0
    assert treasury.balance == 0
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_deposit_event_failure_rolls_back_credit_and_fee(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="tx-event-failure",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    quote = create_quote(user)

    with (
        patch(
            "core.services.convert_deposit.DepositEvent.objects.create",
            side_effect=RuntimeError("event persistence failed"),
        ),
        pytest.raises(RuntimeError, match="event persistence failed"),
    ):
        convert_deposit(deposit, quote)

    deposit.refresh_from_db()
    quote.refresh_from_db()
    assert deposit.state == Deposit.State.CONFIRMED
    assert deposit.conversion_processed_at is None
    assert quote.consumed_at is None
    assert LedgerEntry.objects.count() == 0


@pytest.mark.django_db
def test_deposit_too_small_to_pay_fee_is_not_credited(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="tx-small",
        amount_atomic=1,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    quote = create_quote(user, amount=1, rate=100_000_000)

    with pytest.raises(ValidationError, match="too small"):
        convert_deposit(deposit, quote)

    deposit.refresh_from_db()
    quote.refresh_from_db()
    assert deposit.state == Deposit.State.CONFIRMED
    assert deposit.conversion_processed_at is None
    assert quote.consumed_at is None
    assert LedgerEntry.objects.count() == 0
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_conversion_rejects_expired_quote_without_posting(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    deposit = Deposit.objects.create(
        address=address,
        transaction_id="tx-expired",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    quote = create_quote(
        user,
        locked_until=timezone.now() - timedelta(seconds=1),
    )

    with pytest.raises(ValidationError, match="expired"):
        convert_deposit(deposit, quote)

    assert LedgerEntry.objects.count() == 0
    assert Deposit.objects.get(pk=deposit.pk).state == Deposit.State.CONFIRMED


@pytest.mark.django_db
def test_conversion_rejects_quote_reuse(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    quote = create_quote(user)
    first = Deposit.objects.create(
        address=address,
        transaction_id="tx-once",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )
    second = Deposit.objects.create(
        address=address,
        transaction_id="tx-twice",
        amount_atomic=100_000_000,
        confirmations=2,
        state=Deposit.State.CONFIRMED,
    )

    convert_deposit(first, quote)
    with pytest.raises(ValidationError, match="already been used"):
        convert_deposit(second, quote)

    assert LedgerEntry.objects.filter(ref=f"deposit-{first.pk}").count() == 4
    assert LedgerEntry.objects.filter(ref=f"deposit-{second.pk}").count() == 0


@pytest.mark.django_db
def test_deposit_addresses_and_rate_audit_records_are_immutable(user) -> None:
    address = create_deposit_address(user, Chain.BTC)
    address.address = "changed-address"
    with pytest.raises(ValidationError, match="permanent"):
        address.save()
    with pytest.raises(ValidationError, match="immutable"):
        type(address).objects.filter(pk=address.pk).update(address="changed-address")

    quote = create_quote(user)
    with pytest.raises(ValidationError, match="immutable"):
        type(quote).objects.filter(pk=quote.pk).update(base_units_per_coin=1)

    quote.refresh_from_db()
    quote.consumed_at = timezone.now()
    quote.save(update_fields=("consumed_at",))
    quote.consumed_at = None
    with pytest.raises(ValidationError, match="immutable"):
        quote.save(update_fields=("consumed_at",))


@pytest.mark.django_db
def test_quote_median_is_stored_and_stale_or_divergent_feeds_pause(user) -> None:
    now = timezone.now()
    RateTick.objects.create(
        chain=Chain.BTC,
        source="coinbase",
        base_units_per_coin=10_000_000_000,
        observed_at=now,
    )
    RateTick.objects.create(
        chain=Chain.BTC,
        source="kraken",
        base_units_per_coin=10_050_000_000,
        observed_at=now,
    )
    quote = issue_rate_quote(user, Chain.BTC, 1, 100)
    assert quote.base_units_per_coin == 10_025_000_000
    assert quote.source_a.source == "coinbase"
    assert quote.source_b.source == "kraken"

    RateTick.objects.create(
        chain=Chain.BTC,
        source="coinbase",
        base_units_per_coin=10_000_000_000,
        observed_at=now,
    )
    RateTick.objects.create(
        chain=Chain.BTC,
        source="kraken",
        base_units_per_coin=10_200_000_000,
        observed_at=now,
    )
    with pytest.raises(RateDivergence):
        issue_rate_quote(user, Chain.BTC, 1, 100)

    RateTick.objects.create(
        chain=Chain.LTC,
        source="coinbase",
        base_units_per_coin=10_000_000_000,
        observed_at=now - timedelta(minutes=6),
    )
    RateTick.objects.create(
        chain=Chain.LTC,
        source="kraken",
        base_units_per_coin=10_000_000_000,
        observed_at=now - timedelta(minutes=6),
    )
    with pytest.raises(RateDivergence, match="stale"):
        issue_rate_quote(user, Chain.LTC, 1, 100)


@pytest.mark.django_db
def test_rate_capture_uses_tor_socks_for_both_independent_sources(settings) -> None:
    settings.RATE_FEED_SOCKS_PROXY = "socks5h://127.0.0.1:9050"

    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            return None

        def json(self):
            return self.value

    session = MagicMock()
    session.get.side_effect = [
        Response({"data": {"amount": "100.0"}}),
        Response({"error": [], "result": {"XBTUSD": {"c": ["101.0"]}}}),
    ]
    with patch("payments.providers.rates.requests.Session", return_value=session):
        ticks = capture_rate_feed(Chain.BTC)
    assert [tick.source for tick in ticks] == ["coinbase", "kraken"]
    assert session.get.call_args_list[0].kwargs["proxies"]["https"] == (
        "socks5h://127.0.0.1:9050"
    )
    assert session.get.call_args_list[1].kwargs["proxies"]["https"] == (
        "socks5h://127.0.0.1:9050"
    )


@pytest.mark.django_db
def test_rate_capture_stores_no_tick_when_second_source_fails(settings) -> None:
    settings.RATE_FEED_SOCKS_PROXY = "socks5h://127.0.0.1:9050"

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"amount": "100.0"}}

    session = MagicMock()
    session.get.side_effect = [Response(), RuntimeError("second feed unavailable")]
    with (
        patch("payments.providers.rates.requests.Session", return_value=session),
        pytest.raises(RuntimeError, match="second feed unavailable"),
    ):
        capture_rate_feed(Chain.BTC)

    assert not RateTick.objects.filter(chain=Chain.BTC).exists()


@pytest.mark.django_db
def test_withdrawal_idempotency_caps_and_worker_settlement(user, settings) -> None:
    settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = 100
    settings.MARKET_WITHDRAWAL_MAX_HOURLY_BASE_UNITS = 150
    settings.MARKET_WITHDRAWAL_MAX_DAILY_BASE_UNITS = 200
    vendor_available = Account.objects.create(
        kind=Account.Kind.VENDOR_AVAILABLE,
        owner=user,
    )
    vendor_bond = Account.objects.create(
        kind=Account.Kind.VENDOR_BOND,
        owner=user,
    )
    VendorProfile.objects.create(
        user=user,
        bond_account=vendor_bond,
        is_approved=True,
    )
    _create_ready_payout(user)
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    LedgerEntry.objects.create(account=vendor_available, amount=500, ref="fund-vendor")
    LedgerEntry.objects.create(account=external, amount=-500, ref="fund-vendor")
    with patch("core.services.request_withdrawal.publish_on_commit"):
        withdrawal = request_withdrawal(user, Chain.BTC, TEST_BTC_ADDRESS, 100, "id-1")
        repeated = request_withdrawal(user, Chain.BTC, TEST_BTC_ADDRESS, 100, "id-1")
        over_cap = request_withdrawal(user, Chain.BTC, TEST_BTC_ADDRESS, 60, "id-2")

    assert repeated.pk == withdrawal.pk
    assert withdrawal.state == Withdrawal.State.QUEUED
    assert over_cap.state == Withdrawal.State.MANUAL_APPROVAL
    escrow = Account.objects.get(kind=Account.Kind.USER_ESCROW, owner=user)
    assert escrow.balance == 160
    with pytest.raises(ValidationError, match="Idempotency key"):
        request_withdrawal(
            user,
            Chain.BTC,
            TEST_OTHER_BTC_ADDRESS,
            100,
            "id-1",
        )

    provider = MagicMock()
    provider.send_withdrawal.return_value = "provider-reference"
    with patch(
        "core.services.process_withdrawal.get_chain_provider",
        return_value=provider,
    ):
        completed = process_withdrawal(withdrawal)
    provider.send_withdrawal.assert_called_once_with(
        TEST_BTC_ADDRESS,
        97,
        "id-1",
    )
    assert completed.state == Withdrawal.State.COMPLETED
    assert escrow.balance == 60
    fee = Account.objects.get(kind=Account.Kind.MARKET_FEE, owner__isnull=True)
    assert fee.balance == 3
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_ambiguous_withdrawal_send_is_not_retried(user, settings) -> None:
    available = Account.objects.create(
        kind=Account.Kind.VENDOR_AVAILABLE,
        owner=user,
    )
    bond = Account.objects.create(kind=Account.Kind.VENDOR_BOND, owner=user)
    VendorProfile.objects.create(user=user, bond_account=bond, is_approved=True)
    _create_ready_payout(user)
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    LedgerEntry.objects.create(account=available, amount=100, ref="fund-vendor")
    LedgerEntry.objects.create(account=external, amount=-100, ref="fund-vendor")
    with patch("core.services.request_withdrawal.publish_on_commit"):
        withdrawal = request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            20,
            "ambiguous-send",
        )
    provider = MagicMock()
    provider.send_withdrawal.side_effect = RuntimeError("RPC response was lost")

    with patch(
        "core.services.process_withdrawal.get_chain_provider",
        return_value=provider,
    ):
        with pytest.raises(RuntimeError, match="RPC response was lost"):
            process_withdrawal(withdrawal)
        withdrawal.refresh_from_db()
        assert withdrawal.provider_reference.startswith("pending-send:")
        with pytest.raises(ValidationError, match="outcome is unresolved"):
            process_withdrawal(withdrawal)

    provider.send_withdrawal.assert_called_once()


@pytest.mark.django_db
def test_withdrawal_rejects_insufficient_funds_and_uses_manual_approval(
    user, settings
) -> None:
    settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = 10
    account = Account.objects.create(kind=Account.Kind.VENDOR_AVAILABLE, owner=user)
    vendor_bond = Account.objects.create(
        kind=Account.Kind.VENDOR_BOND,
        owner=user,
    )
    VendorProfile.objects.create(
        user=user,
        bond_account=vendor_bond,
        is_approved=True,
    )
    _create_ready_payout(user)
    with pytest.raises(InsufficientFunds):
        request_withdrawal(user, Chain.BTC, TEST_BTC_ADDRESS, 20, "too-large")
    assert not Withdrawal.objects.exists()
    LedgerEntry.objects.create(account=account, amount=100, ref="opening")
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    LedgerEntry.objects.create(account=external, amount=-100, ref="opening")
    with patch("core.services.request_withdrawal.publish_on_commit"):
        withdrawal = request_withdrawal(user, Chain.BTC, TEST_BTC_ADDRESS, 20, "cap")
    assert withdrawal.state == Withdrawal.State.MANUAL_APPROVAL
    with (
        patch("core.services.process_withdrawal.get_chain_provider") as provider,
        pytest.raises(ValueError, match="requires manual approval"),
    ):
        process_withdrawal(withdrawal)
    provider.assert_not_called()


@pytest.mark.django_db
def test_manual_withdrawal_requires_admin_approval(user, settings, admin_user) -> None:
    settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = 10
    vendor_available = Account.objects.create(
        kind=Account.Kind.VENDOR_AVAILABLE,
        owner=user,
    )
    bond = Account.objects.create(kind=Account.Kind.VENDOR_BOND, owner=user)
    VendorProfile.objects.create(user=user, bond_account=bond, is_approved=True)
    _create_ready_payout(user)
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    LedgerEntry.objects.create(account=vendor_available, amount=100, ref="fund-vendor")
    LedgerEntry.objects.create(account=external, amount=-100, ref="fund-vendor")
    with patch("core.services.request_withdrawal.publish_on_commit"):
        withdrawal = request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            20,
            "manual",
        )

    with pytest.raises(PermissionDenied):
        approve_withdrawal(withdrawal, user)
    with patch("core.services.approve_withdrawal.publish_on_commit"):
        approved = approve_withdrawal(withdrawal, admin_user)
    assert approved.state == Withdrawal.State.APPROVED


@pytest.mark.django_db
def test_rejected_manual_withdrawal_refunds_gross_without_charging_fee(
    user,
    settings,
    admin_user,
) -> None:
    settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = 10
    available = Account.objects.create(
        kind=Account.Kind.USER_AVAILABLE,
        owner=user,
    )
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    LedgerEntry.objects.create(account=available, amount=500, ref="fund-user")
    LedgerEntry.objects.create(account=external, amount=-500, ref="fund-user")
    _create_ready_payout(user)
    with patch("core.services.request_withdrawal.publish_on_commit"):
        withdrawal = request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            100,
            "manual-rejection",
        )

    rejected = reject_withdrawal(withdrawal, admin_user, "Please verify your request.")

    available.refresh_from_db()
    escrow = Account.objects.get(kind=Account.Kind.USER_ESCROW, owner=user)
    market_fee = Account.objects.get(kind=Account.Kind.MARKET_FEE, owner__isnull=True)
    assert rejected.state == Withdrawal.State.REJECTED
    assert rejected.rejection_reason == "Please verify your request."
    assert available.balance == 500
    assert escrow.balance == 0
    assert market_fee.balance == 0
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_withdrawal_kill_switch_blocks_requests_and_worker_sends(
    user, settings
) -> None:
    available = Account.objects.create(
        kind=Account.Kind.VENDOR_AVAILABLE,
        owner=user,
    )
    bond = Account.objects.create(kind=Account.Kind.VENDOR_BOND, owner=user)
    VendorProfile.objects.create(user=user, bond_account=bond, is_approved=True)
    _create_ready_payout(user)
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    LedgerEntry.objects.create(account=available, amount=100, ref="fund-vendor")
    LedgerEntry.objects.create(account=external, amount=-100, ref="fund-vendor")
    with patch("core.services.request_withdrawal.publish_on_commit"):
        withdrawal = request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            20,
            "before-kill-switch",
        )

    set_market_feature("withdrawals", False)
    with pytest.raises(ValidationError, match="temporarily paused"):
        request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            20,
            "after-kill-switch",
        )

    with (
        patch("core.services.process_withdrawal.get_chain_provider") as get_provider,
        pytest.raises(ValidationError, match="temporarily paused"),
    ):
        process_withdrawal(withdrawal)
    get_provider.assert_not_called()
    assert reconcile_ledger() == 0


@pytest.mark.django_db
def test_daily_fee_sweep_moves_fee_and_spread_to_treasury_once(capsys) -> None:
    fee = Account.objects.get(kind=Account.Kind.MARKET_FEE, owner__isnull=True)
    spread = Account.objects.get(
        kind=Account.Kind.MARKET_SPREAD,
        owner__isnull=True,
    )
    treasury = Account.objects.get(kind=Account.Kind.TREASURY, owner__isnull=True)
    external = Account.objects.get(kind=Account.Kind.EXTERNAL, owner__isnull=True)
    for account, amount, reference in (
        (fee, 40, "fee-before-sweep"),
        (spread, 60, "spread-before-sweep"),
    ):
        LedgerEntry.objects.create(account=account, amount=amount, ref=reference)
        LedgerEntry.objects.create(account=external, amount=-amount, ref=reference)
    treasury_before = treasury.balance

    call_command("sweep_market_fees")
    first_sweep_entry_count = LedgerEntry.objects.filter(
        ref__startswith="daily-market-fee-sweep-"
    ).count()
    swept_again = sweep_market_fees()

    fee.refresh_from_db()
    spread.refresh_from_db()
    treasury.refresh_from_db()
    assert swept_again == 0
    assert fee.balance == spread.balance == 0
    assert treasury.balance == treasury_before + 100
    assert (
        LedgerEntry.objects.filter(ref__startswith="daily-market-fee-sweep-").count()
        == first_sweep_entry_count
        == 4
    )
    assert "Swept 100 base units" in capsys.readouterr().out
    assert reconcile_ledger() == 0


def _configure_monero_rpc(settings) -> None:
    settings.MONERO_RESERVE_WALLET_RPC_URL = "http://127.0.0.1:18083/json_rpc"
    settings.MONERO_HOT_WALLET_RPC_URL = "http://127.0.0.1:18084/json_rpc"
    settings.MONERO_PAYOUT_WALLET_RPC_URL = "http://127.0.0.1:18085/json_rpc"
    settings.MONERO_RESERVE_WALLET_RPC_USER = "reserve"
    settings.MONERO_RESERVE_WALLET_RPC_PASSWORD = "reserve-password"
    settings.MONERO_HOT_WALLET_RPC_USER = "hot"
    settings.MONERO_HOT_WALLET_RPC_PASSWORD = "hot-password"
    settings.MONERO_PAYOUT_WALLET_RPC_USER = "payout"
    settings.MONERO_PAYOUT_WALLET_RPC_PASSWORD = "payout-password"


@pytest.mark.django_db
def test_monero_reserve_rpc_rejects_all_send_methods(settings) -> None:
    _configure_monero_rpc(settings)
    provider = MoneroWalletProvider()

    with pytest.raises(
        ProviderError,
        match="reserve Monero wallet does not permit transfer",
    ):
        provider._rpc("reserve", "transfer", {})


@pytest.mark.django_db
def test_monero_boot_probe_requires_local_daemon_and_checks_reserve(settings) -> None:
    _configure_monero_rpc(settings)
    settings.MONEROD_RPC_URL = "http://127.0.0.1:18081/get_info"
    settings.RATE_FEED_TIMEOUT_SECONDS = 1
    provider = MoneroWalletProvider()
    with patch.object(provider.daemon_session, "post") as daemon_post:
        daemon_post.return_value.json.return_value = {"height": 42}
        with patch.object(
            provider,
            "_rpc",
            return_value={"balance": 500, "unlocked_balance": 200},
        ) as wallet_rpc:
            provider.validate_at_startup()

    assert wallet_rpc.call_args.args == (
        "reserve",
        "get_balance",
        {"account_index": 0},
    )
    daemon_post.assert_called_once()

    settings.MONEROD_RPC_URL = "https://public-node.example/json_rpc"
    with pytest.raises(ImproperlyConfigured, match="localhost RPC"):
        provider.validate_at_startup()


@pytest.mark.django_db
def test_monero_sweep_uses_hot_wallet_and_primary_hot_address(user, settings) -> None:
    _configure_monero_rpc(settings)
    DepositAddress.objects.create(
        user=user,
        chain=Chain.XMR,
        address="4" + ("1" * 94),
        provider_reference="9",
    )
    provider = MoneroWalletProvider()
    with patch.object(
        provider,
        "_rpc",
        side_effect=[
            {"unlocked_balance": 100},
            {"address": "hot-primary-address"},
            {"tx_hash_list": ["sweep-tx"]},
        ],
    ) as wallet_rpc:
        assert provider.sweep_to_hot() == 1

    sweep_call = wallet_rpc.call_args_list[-1]
    assert sweep_call.args[:2] == ("hot", "sweep_all")
    assert sweep_call.args[2]["subaddr_indices"] == [9]
    assert sweep_call.args[2]["address"] == "hot-primary-address"
    assert all(call.args[0] == "hot" for call in wallet_rpc.call_args_list)


@pytest.mark.django_db
def test_monero_withdrawal_broadcast_uses_payout_wallet_only(settings) -> None:
    _configure_monero_rpc(settings)
    provider = MoneroWalletProvider()
    now = timezone.now()
    for source in ("coinbase", "kraken"):
        RateTick.objects.create(
            chain=Chain.XMR,
            source=source,
            base_units_per_coin=100_000_000,
            observed_at=now,
        )

    with patch.object(
        provider,
        "_rpc",
        return_value={"tx_hash": "payout-tx"},
    ) as wallet_rpc:
        transaction_id = provider.send_withdrawal(
            "destination",
            100_000_000,
            "withdrawal-key",
        )

    assert transaction_id == "payout-tx"
    assert wallet_rpc.call_args.args[:2] == ("payout", "transfer")
    assert wallet_rpc.call_args.args[2]["destinations"] == [
        {"address": "destination", "amount": 10**12}
    ]


@pytest.mark.django_db
def test_monero_creates_per_user_deposit_subaddress_in_hot_wallet(
    user,
    settings,
) -> None:
    _configure_monero_rpc(settings)
    provider = MoneroWalletProvider()
    with patch.object(
        provider,
        "_rpc",
        return_value={"address": "user-subaddress", "address_index": 11},
    ) as wallet_rpc:
        address, reference = provider.new_address(user, Chain.XMR)

    assert (address, reference) == ("user-subaddress", "11")
    assert wallet_rpc.call_args.args[:2] == ("hot", "create_address")


@pytest.mark.django_db
def test_monero_balance_reads_reserve_and_hot_but_not_payout(settings) -> None:
    _configure_monero_rpc(settings)
    provider = MoneroWalletProvider()
    with patch.object(
        provider,
        "_rpc",
        side_effect=[
            {"balance": 300, "unlocked_balance": 200},
            {"balance": 700, "unlocked_balance": 600},
        ],
    ) as wallet_rpc:
        assert provider.wallet_balance() == 1_000

    assert [call.args[0] for call in wallet_rpc.call_args_list] == [
        "reserve",
        "hot",
    ]


@pytest.mark.django_db
def test_btcpay_balance_sums_confirmed_and_unconfirmed_wallet_amounts(
    settings,
) -> None:
    settings.BTCPAY_SERVER_URL = "https://btcpay.example"
    settings.BTCPAY_STORE_ID = "store"
    settings.BTCPAY_API_KEY = "api-key"
    provider = BTCPayProvider(Chain.BTC)
    with patch.object(
        provider,
        "_request",
        side_effect=[
            {"derivationScheme": "xpub/0"},
            {"confirmed": "0.1", "unconfirmed": "0.02"},
        ],
    ) as request:
        assert provider.wallet_balance() == 12_000_000

    assert "%2F" in request.call_args_list[1].args[1]


@pytest.mark.django_db
def test_trongrid_balance_uses_trc20_balance_of_for_known_deposit_addresses(
    user,
    settings,
) -> None:
    settings.TRONGRID_API_URL = "https://api.trongrid.io"
    settings.TRC20_CONTRACT_WHITELIST = [settings.TETHER_TRC20_CONTRACT]
    settings.TRON_ADDRESS_DERIVER = "payments.tests:unused_address_deriver"
    settings.TRC20_TOKEN_DECIMALS = 6
    address = _tron_test_key().public_key.to_base58check_address()
    DepositAddress.objects.create(
        user=user,
        chain=Chain.TRC20,
        address=address,
        provider_reference="local-wallet",
    )
    provider = TronGridProvider()
    with patch.object(
        provider,
        "_request",
        return_value={"result": {"result": True}, "constant_result": ["1a"]},
    ) as request:
        assert provider.wallet_balance() == 26

    assert request.call_args.args[1] == "/wallet/triggerconstantcontract"
    assert request.call_args.kwargs["json"]["function_selector"] == "balanceOf(address)"


@pytest.mark.django_db
def test_trongrid_scans_three_cursor_pages_and_commits_block_watermark(
    user,
    settings,
) -> None:
    settings.TRONGRID_API_URL = "https://api.trongrid.io"
    settings.TRC20_CONTRACT_WHITELIST = [settings.TETHER_TRC20_CONTRACT]
    settings.TRON_ADDRESS_DERIVER = "payments.tests:unused_address_deriver"
    settings.TRC20_TOKEN_DECIMALS = 6
    address = _tron_test_key().public_key.to_base58check_address()
    DepositAddress.objects.create(
        user=user,
        chain=Chain.TRC20,
        address=address,
        provider_reference="local-wallet",
    )
    watermark = ChainPollWatermark.objects.create(
        provider="trongrid",
        chain=Chain.TRC20,
        last_block=100,
    )
    contract = settings.TETHER_TRC20_CONTRACT

    def item(transaction_id: str, destination: str) -> dict:
        return {
            "transaction_id": transaction_id,
            "token_info": {
                "address": contract,
                "decimals": 6,
                "symbol": settings.TRC20_RATE_SYMBOL,
            },
            "from": _tron_test_key("22").public_key.to_base58check_address(),
            "to": destination,
            "value": "1000",
        }

    other_address = _tron_test_key("33").public_key.to_base58check_address()
    pages = [
        {
            "data": [
                item(f"irrelevant-{index}", other_address) for index in range(200)
            ],
            "meta": {"fingerprint": "page-2"},
        },
        {
            "data": [
                *[item(f"irrelevant-2-{index}", other_address) for index in range(199)],
                item("old-transfer", address),
            ],
            "meta": {"fingerprint": "page-3"},
        },
        {
            "data": [
                *[item(f"irrelevant-3-{index}", other_address) for index in range(199)],
                item("new-transfer", address),
            ],
            "meta": {"links": {}},
        },
    ]
    page_requests = []

    def request(method: str, path: str, **kwargs):
        if path == "/wallet/getnowblock":
            return {"block": {"block_header": {"raw_data": {"number": 150}}}}
        if path.endswith("/transactions/trc20"):
            page_requests.append(kwargs["params"])
            return pages.pop(0)
        if path == "/wallet/gettransactioninfobyid":
            block_number = {
                "old-transfer": 100,
                "new-transfer": 101,
            }[kwargs["json"]["value"]]
            return {"blockNumber": block_number}
        raise AssertionError(f"Unexpected TronGrid request: {method} {path}")

    provider = TronGridProvider()
    with (
        patch.object(provider, "_request", side_effect=request),
        patch.object(provider, "_is_tether_blacklisted", return_value=False),
    ):
        transfers = list(provider.poll())
        assert [transfer.transaction_id for transfer in transfers] == ["new-transfer"]
        provider.commit_poll()

    watermark.refresh_from_db()
    assert watermark.last_block == 150
    assert len(page_requests) == 3
    assert [params.get("fingerprint") for params in page_requests] == [
        None,
        "page-2",
        "page-3",
    ]
    assert not pages


@pytest.mark.django_db
def test_trongrid_does_not_advance_watermark_when_recording_fails(
    user,
    settings,
) -> None:
    settings.TRONGRID_API_URL = "https://api.trongrid.io"
    settings.TRC20_CONTRACT_WHITELIST = [settings.TETHER_TRC20_CONTRACT]
    settings.TRON_ADDRESS_DERIVER = "payments.tests:unused_address_deriver"
    settings.TRC20_TOKEN_DECIMALS = 6
    address = _tron_test_key().public_key.to_base58check_address()
    DepositAddress.objects.create(
        user=user,
        chain=Chain.TRC20,
        address=address,
        provider_reference="local-wallet",
    )
    watermark = ChainPollWatermark.objects.create(
        provider="trongrid",
        chain=Chain.TRC20,
        last_block=100,
    )
    provider = TronGridProvider()
    page = {
        "data": [
            {
                "transaction_id": "unrecorded-transfer",
                "token_info": {
                    "address": settings.TETHER_TRC20_CONTRACT,
                    "decimals": 6,
                    "symbol": settings.TRC20_RATE_SYMBOL,
                },
                "from": _tron_test_key("22").public_key.to_base58check_address(),
                "to": address,
                "value": "1000",
            }
        ],
        "meta": {"links": {}},
    }

    def request(method: str, path: str, **kwargs):
        if path == "/wallet/getnowblock":
            return {"block": {"block_header": {"raw_data": {"number": 101}}}}
        if path.endswith("/transactions/trc20"):
            return page
        if path == "/wallet/gettransactioninfobyid":
            return {"blockNumber": 101}
        raise AssertionError(f"Unexpected TronGrid request: {method} {path}")

    with (
        patch("core.services.poll_deposits.get_chain_provider", return_value=provider),
        patch.object(provider, "_request", side_effect=request),
        patch.object(provider, "_is_tether_blacklisted", return_value=False),
        patch(
            "core.services.poll_deposits.record_deposit_transfer",
            side_effect=ProviderError("recording failed"),
        ),
        pytest.raises(ProviderError, match="recording failed"),
    ):
        poll_deposits(Chain.TRC20)

    watermark.refresh_from_db()
    assert watermark.last_block == 100


def test_trongrid_retries_failed_requests_with_three_delays(settings) -> None:
    settings.TRONGRID_API_URL = "https://api.trongrid.io"
    settings.TRC20_CONTRACT_WHITELIST = [settings.TETHER_TRC20_CONTRACT]
    settings.TRON_ADDRESS_DERIVER = "payments.tests:unused_address_deriver"
    provider = TronGridProvider()
    response = MagicMock()
    response.json.return_value = {"ok": True}
    with (
        patch.object(
            provider.session,
            "request",
            side_effect=[
                requests.ConnectionError("temporary"),
                requests.ConnectionError("temporary"),
                requests.ConnectionError("temporary"),
                response,
            ],
        ) as request,
        patch("payments.providers.trongrid.sleep") as wait,
    ):
        assert provider._request("GET", "/health") == {"ok": True}

    assert request.call_count == 4
    assert [call.args[0] for call in wait.call_args_list] == [1, 5, 25]


@pytest.mark.django_db
def test_withdrawal_rejects_provider_without_withdrawal_support(user) -> None:
    provider = MagicMock(supports_withdrawal=False, supports_withdrawals=False)
    with (
        patch(
            "core.services.request_withdrawal.get_chain_provider",
            return_value=provider,
        ),
        pytest.raises(ValidationError, match="does not support withdrawals"),
    ):
        request_withdrawal(
            user,
            Chain.BTC,
            TEST_BTC_ADDRESS,
            100,
            "unsupported-provider",
        )

    assert not Withdrawal.objects.filter(user=user).exists()


def test_fake_wallet_balance_is_settable_across_provider_instances() -> None:
    provider = FakeProvider(Chain.LTC)
    provider.set_wallet_balance(1234)

    assert FakeProvider(Chain.LTC).wallet_balance() == 1234


def test_monero_sweep_service_delegates_to_provider_and_surfaces_errors() -> None:
    provider = FakeProvider(Chain.XMR)
    with patch(
        "core.services.sweep_monero_deposits.get_chain_provider",
        return_value=provider,
    ):
        assert sweep_monero_deposits() == 0
        assert provider.last_sweep_destination == "fake-hot-xmr"

        with (
            patch.object(
                provider,
                "sweep_to_hot",
                side_effect=ProviderError("Monero RPC unavailable."),
            ),
            pytest.raises(ProviderError, match="Monero RPC unavailable"),
        ):
            sweep_monero_deposits()
