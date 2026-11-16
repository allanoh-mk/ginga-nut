import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.forms import (
    DepositAddressForm,
    LoginForm,
    PayoutAddressForm,
    PGPChallengeForm,
    PGPEnrollmentForm,
    ProfileForm,
    RecoveryLoginForm,
    RegistrationForm,
    WalletAddressForm,
    WalletSignatureForm,
    WithdrawalForm,
)
from accounts.models import User
from core.services.authenticate_user import LoginRateLimited, authenticate_user
from core.services.convert_deposit import convert_deposit
from core.services.create_deposit_address import create_deposit_address
from core.services.create_payout_address_challenge import (
    create_payout_address_challenge,
)
from core.services.create_wallet_link_challenge import create_wallet_link_challenge
from core.services.delete_payout_address import delete_payout_address
from core.services.get_available_balance import get_available_balance
from core.services.issue_rate_quote import issue_rate_quote
from core.services.market_commission import calculate_market_commission
from core.services.pgp_auth import (
    consume_recovery_code,
    create_recovery_codes,
    verify_openpgp_signature,
)
from core.services.register_user import register_user
from core.services.request_withdrawal import request_withdrawal
from core.services.save_payout_address import save_payout_address
from core.services.unlink_wallet import unlink_wallet
from core.services.update_session_expiry import update_session_expiry
from core.services.verify_payout_address_challenge import (
    verify_payout_address_challenge,
)
from core.services.verify_wallet_link_challenge import verify_wallet_link_challenge
from ledger.exceptions import InsufficientFunds
from payments.models import (
    Deposit,
    DepositAddress,
    PayoutAddress,
    PayoutAddressChallenge,
    RateQuote,
    WalletLink,
    WalletLinkChallenge,
    Withdrawal,
)
from payments.providers import get_chain_provider

PGP_FLOW_SESSION_KEY = "pending_pgp_auth"
PGP_CHALLENGE_LIFETIME_SECONDS = 5 * 60
PGP_MAX_ATTEMPTS = 5


def _challenge_message(challenge: str) -> str:
    return f"Kola Market OpenPGP authentication\n{challenge}\n"


def _begin_pgp_flow(request, user: User, mode: str) -> None:
    request.session[PGP_FLOW_SESSION_KEY] = {
        "user_id": user.pk,
        "mode": mode,
        "challenge": secrets.token_urlsafe(32),
        "created_at": int(time.time()),
        "attempts": 0,
    }
    request.session.set_expiry(PGP_CHALLENGE_LIFETIME_SECONDS)


def _pending_pgp_flow(request) -> tuple[dict, User] | None:
    flow = request.session.get(PGP_FLOW_SESSION_KEY)
    if not isinstance(flow, dict):
        return None
    created_at = flow.get("created_at")
    if (
        not isinstance(created_at, int)
        or int(time.time()) - created_at > PGP_CHALLENGE_LIFETIME_SECONDS
    ):
        request.session.pop(PGP_FLOW_SESSION_KEY, None)
        return None
    try:
        user = User.objects.get(pk=flow.get("user_id"), is_active=True)
    except (TypeError, ValueError, User.DoesNotExist):
        request.session.pop(PGP_FLOW_SESSION_KEY, None)
        return None
    return flow, user


def _complete_login(request, user: User):
    request.session.pop(PGP_FLOW_SESSION_KEY, None)
    login(
        request,
        user,
        backend="django.contrib.auth.backends.ModelBackend",
    )
    request.session["pgp_verified_user_id"] = user.pk
    request.session.set_expiry(user.session_expiry_seconds)
    return redirect("accounts:profile")


@never_cache
@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = register_user(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password1"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            _begin_pgp_flow(request, user, "enroll")
            return redirect("accounts:pgp_auth")

    return render(
        request,
        "accounts/register.html",
        {"form": form},
        status=400 if request.method == "POST" and form.errors else 200,
    )


@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")

    form = LoginForm(request.POST or None)
    locked_out = False
    if request.method == "POST" and form.is_valid():
        try:
            user = authenticate_user(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
                remote_addr=request.META.get("REMOTE_ADDR", ""),
            )
        except LoginRateLimited:
            locked_out = True
        else:
            if user is not None:
                mode = "login" if user.pgp_public_key else "enroll"
                _begin_pgp_flow(request, user, mode)
                return redirect("accounts:pgp_auth")
            form.add_error(None, "Invalid username or password.")

    return render(
        request,
        "accounts/login.html",
        {"form": form, "locked_out": locked_out},
        status=429
        if locked_out
        else (400 if request.method == "POST" and form.errors else 200),
    )


@never_cache
@require_http_methods(["GET", "POST"])
def recovery_login_view(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    form = RecoveryLoginForm(request.POST or None)
    locked_out = False
    if request.method == "POST" and form.is_valid():
        try:
            user = authenticate_user(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
                remote_addr=request.META.get("REMOTE_ADDR", ""),
            )
        except LoginRateLimited:
            locked_out = True
        else:
            if user is not None and user.pgp_public_key:
                recovered_user = consume_recovery_code(
                    user.pk,
                    form.cleaned_data["recovery_code"],
                )
                if recovered_user is not None:
                    login(
                        request,
                        user,
                        backend="django.contrib.auth.backends.ModelBackend",
                    )
                    request.session["pgp_verified_user_id"] = user.pk
                    request.session.set_expiry(user.session_expiry_seconds)
                    return redirect("accounts:profile")
            form.add_error(None, "The sign-in details or recovery code are incorrect.")
    return render(
        request,
        "accounts/recovery_login.html",
        {"form": form, "locked_out": locked_out},
        status=429
        if locked_out
        else (400 if request.method == "POST" and form.errors else 200),
    )


@never_cache
@require_http_methods(["GET", "POST"])
def pgp_auth_view(request):
    pending = _pending_pgp_flow(request)
    if pending is None:
        return redirect("accounts:login")
    flow, user = pending
    mode = flow.get("mode")
    if mode not in {"enroll", "login", "regenerate"}:
        request.session.pop(PGP_FLOW_SESSION_KEY, None)
        return redirect("accounts:login")
    if mode == "enroll" and user.pgp_public_key:
        request.session.pop(PGP_FLOW_SESSION_KEY, None)
        return redirect("accounts:login")
    if mode == "login" and not user.pgp_public_key:
        request.session.pop(PGP_FLOW_SESSION_KEY, None)
        return redirect("accounts:login")
    if mode == "regenerate" and (
        not request.user.is_authenticated or request.user.pk != user.pk
    ):
        request.session.pop(PGP_FLOW_SESSION_KEY, None)
        return redirect("accounts:login")

    form_class = PGPEnrollmentForm if mode == "enroll" else PGPChallengeForm
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        message = _challenge_message(flow["challenge"])
        if mode == "enroll":
            public_key = form.cleaned_data["public_key"].strip()
            fingerprint = verify_openpgp_signature(
                public_key,
                form.cleaned_data["signature"],
                message,
            )
            if fingerprint is None:
                flow["attempts"] = int(flow.get("attempts", 0)) + 1
                if flow["attempts"] >= PGP_MAX_ATTEMPTS:
                    request.session.pop(PGP_FLOW_SESSION_KEY, None)
                    return redirect("accounts:login")
                request.session[PGP_FLOW_SESSION_KEY] = flow
                form.add_error(
                    None,
                    (
                        "The public key or signature is invalid. Sign the current "
                        "challenge with the matching private key."
                    ),
                )
            else:
                recovery_codes, recovery_hashes = create_recovery_codes()
                user.pgp_public_key = public_key
                user.pgp_fingerprint = fingerprint
                user.pgp_recovery_code_hashes = recovery_hashes
                user.save(
                    update_fields=(
                        "pgp_public_key",
                        "pgp_fingerprint",
                        "pgp_recovery_code_hashes",
                    )
                )
                _complete_login(request, user)
                return render(
                    request,
                    "accounts/pgp_recovery_codes.html",
                    {"recovery_codes": recovery_codes},
                )
        else:
            used_recovery_code = False
            if form.cleaned_data["recovery_code"]:
                recovered_user = consume_recovery_code(
                    user.pk,
                    form.cleaned_data["recovery_code"],
                )
                if recovered_user is not None:
                    used_recovery_code = True
            else:
                fingerprint = verify_openpgp_signature(
                    user.pgp_public_key,
                    form.cleaned_data["signature"],
                    message,
                    expected_fingerprint=user.pgp_fingerprint,
                )
                used_recovery_code = fingerprint is not None

            if not used_recovery_code:
                flow["attempts"] = int(flow.get("attempts", 0)) + 1
                if flow["attempts"] >= PGP_MAX_ATTEMPTS:
                    request.session.pop(PGP_FLOW_SESSION_KEY, None)
                    return render(
                        request,
                        "accounts/login.html",
                        {
                            "form": LoginForm(),
                            "locked_out": True,
                            "message": "OpenPGP verification failed. Sign in again.",
                        },
                        status=429,
                    )
                request.session[PGP_FLOW_SESSION_KEY] = flow
                form.add_error(None, "OpenPGP verification failed.")
            elif mode == "login":
                return _complete_login(request, user)
            else:
                recovery_codes, recovery_hashes = create_recovery_codes()
                user.pgp_recovery_code_hashes = recovery_hashes
                user.save(update_fields=("pgp_recovery_code_hashes",))
                request.session.pop(PGP_FLOW_SESSION_KEY, None)
                request.session.set_expiry(user.session_expiry_seconds)
                return render(
                    request,
                    "accounts/pgp_recovery_codes.html",
                    {"recovery_codes": recovery_codes},
                )

    return render(
        request,
        "accounts/pgp_auth.html",
        {
            "form": form,
            "challenge": _challenge_message(flow["challenge"]),
            "enrollment": mode == "enroll",
            "regenerating_codes": mode == "regenerate",
        },
        status=400 if request.method == "POST" and form.errors else 200,
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
@require_GET
def logout_confirm_view(request):
    return render(request, "accounts/logout_confirm.html")


@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = update_session_expiry(
            request.user,
            form.cleaned_data["session_expiry_seconds"],
        )
        request.session.set_expiry(user.session_expiry_seconds)
        return redirect("accounts:profile")

    return render(
        request,
        "accounts/profile.html",
        {
            "form": form,
            "wallet_link_count": WalletLink.objects.filter(
                user=request.user,
                unlinked_at__isnull=True,
            ).count(),
        },
    )


@never_cache
@login_required
@require_GET
def balance_overview_view(request):
    return render(
        request,
        "accounts/balance.html",
        {
            "available_balance": get_available_balance(request.user),
            "held_balance": _held_balance(request.user),
        },
    )


def _held_balance(user):
    from ledger.models import Account

    escrow = Account.objects.filter(
        owner=user,
        kind=Account.Kind.USER_ESCROW,
    ).first()
    return max(escrow.balance, 0) if escrow else 0


def _deposit_address_list(user):
    addresses = list(
        DepositAddress.objects.filter(user=user)
        .prefetch_related(
            Prefetch(
                "deposits",
                queryset=Deposit.objects.order_by("-created_at", "-pk")[:5],
                to_attr="recent_deposits",
            )
        )
        .order_by("chain", "pk")
    )
    for address in addresses:
        address.confirmation_depth = settings.MARKET_CHAIN_CONFIRMATIONS[address.chain]
    return addresses


@never_cache
@login_required
@require_http_methods(["GET"])
def deposit_addresses_view(request):
    addresses = _deposit_address_list(request.user)
    return render(
        request,
        "accounts/deposits.html",
        {
            "addresses": addresses,
            "form": DepositAddressForm(),
            "available_balance": get_available_balance(request.user),
            "held_balance": _held_balance(request.user),
        },
    )


@never_cache
@login_required
@require_POST
def deposit_address_create(request):
    form = DepositAddressForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "accounts/deposits.html",
            {
                "addresses": _deposit_address_list(request.user),
                "form": form,
                "available_balance": get_available_balance(request.user),
                "held_balance": _held_balance(request.user),
            },
            status=400,
        )
    try:
        address = create_deposit_address(
            request.user,
            form.cleaned_data["chain"],
        )
    except (ValidationError, ValueError) as exc:
        form.add_error(None, exc)
        return render(
            request,
            "accounts/deposits.html",
            {
                "addresses": _deposit_address_list(request.user),
                "form": form,
                "available_balance": get_available_balance(request.user),
                "held_balance": _held_balance(request.user),
            },
            status=400,
        )
    messages.success(request, f"Deposit address ready: {address.address}")
    return redirect("accounts:deposits")


@never_cache
@login_required
@require_GET
def deposit_history(request):
    deposits = (
        Deposit.objects.filter(address__user=request.user)
        .select_related("address")
        .order_by("-created_at", "-pk")
    )
    page = Paginator(deposits, 25).get_page(request.GET.get("page"))
    return render(request, "accounts/deposit_history.html", {"page_obj": page})


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def deposit_quote_convert_view(request, deposit_id: int):
    deposit = get_object_or_404(
        Deposit.objects.select_related("address", "quote"),
        pk=deposit_id,
        address__user=request.user,
        state=Deposit.State.CONFIRMED,
        conversion_processed_at__isnull=True,
        blacklisted=False,
    )
    quote = None
    preview = None
    error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "quote":
                quote = issue_rate_quote(
                    request.user,
                    deposit.address.chain,
                    deposit.amount_atomic,
                    deposit.amount_atomic,
                )
            elif action == "convert":
                quote = RateQuote.objects.get(
                    pk=request.POST.get("quote_id"),
                    user=request.user,
                    chain=deposit.address.chain,
                )
                convert_deposit(deposit, quote)
                messages.success(
                    request, "Deposit converted to your available balance."
                )
                return redirect("accounts:deposit_history")
            else:
                raise ValidationError("Choose a quote or conversion action.")
        except (ValidationError, ValueError, RateQuote.DoesNotExist) as exc:
            error = (
                "; ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else str(exc)
            )
    if quote is not None:
        decimals = get_chain_provider(deposit.address.chain).decimals
        gross = deposit.amount_atomic * quote.base_units_per_coin // (10**decimals)
        try:
            fee, net = calculate_market_commission(gross)
            preview = {"gross": gross, "fee": fee, "net": net}
        except ValidationError as exc:
            error = "; ".join(exc.messages)
    return render(
        request,
        "accounts/deposit_quote.html",
        {"deposit": deposit, "quote": quote, "preview": preview, "error": error},
        status=400 if request.method == "POST" and error else 200,
    )


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def withdrawal_history_view(request):
    available_balance = get_available_balance(request.user)
    form = WithdrawalForm(
        request.POST or None,
        user=request.user,
        available_balance=available_balance,
        initial={"idempotency_key": secrets.token_urlsafe(32)},
    )
    if request.method == "POST" and form.is_valid():
        payout = form.cleaned_data["payout_address"]
        try:
            withdrawal = request_withdrawal(
                request.user,
                payout.chain,
                payout.address,
                form.cleaned_data["amount"],
                form.cleaned_data["idempotency_key"],
            )
        except (ValidationError, InsufficientFunds) as exc:
            form.add_error(None, exc)
        else:
            if withdrawal.state == Withdrawal.State.MANUAL_APPROVAL:
                messages.info(
                    request,
                    "Your withdrawal is pending staff approval.",
                )
            else:
                messages.success(request, "Your withdrawal request was queued.")
            return redirect(
                "accounts:withdrawal_detail",
                withdrawal_id=withdrawal.pk,
            )

    withdrawals = Withdrawal.objects.filter(user=request.user).order_by(
        "-created_at",
        "-pk",
    )
    page = Paginator(withdrawals, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/withdrawals.html",
        {
            "form": form,
            "page_obj": page,
            "available_balance": available_balance,
            "held_balance": _held_balance(request.user),
            "max_transaction_base_units": settings.MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS,
            "max_hourly_base_units": settings.MARKET_WITHDRAWAL_MAX_HOURLY_BASE_UNITS,
            "max_daily_base_units": settings.MARKET_WITHDRAWAL_MAX_DAILY_BASE_UNITS,
        },
        status=400 if request.method == "POST" and form.errors else 200,
    )


@never_cache
@login_required
@require_GET
def withdrawal_detail_view(request, withdrawal_id: int):
    withdrawal = get_object_or_404(
        Withdrawal,
        pk=withdrawal_id,
        user=request.user,
    )
    return render(
        request,
        "accounts/withdrawal_detail.html",
        {"withdrawal": withdrawal},
    )


def _wallets_context(user, form=None, error=None) -> dict[str, object]:
    return {
        "form": form or WalletAddressForm(),
        "wallet_links": WalletLink.objects.filter(user=user),
        "error": error,
    }


@never_cache
@login_required
@require_http_methods(["GET"])
def wallets_view(request):
    return render(
        request,
        "accounts/wallets.html",
        _wallets_context(request.user),
    )


@never_cache
@login_required
@require_POST
def wallet_challenge_start_view(request):
    form = WalletAddressForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "accounts/wallets.html",
            _wallets_context(request.user, form=form),
            status=400,
        )
    try:
        challenge = create_wallet_link_challenge(
            request.user,
            WalletLink.Chain.TRC20,
            form.cleaned_data["address"],
        )
    except ValidationError as exc:
        form.add_error("address", exc)
        return render(
            request,
            "accounts/wallets.html",
            _wallets_context(request.user, form=form),
            status=400,
        )
    return redirect(
        "accounts:wallet_challenge",
        challenge_id=challenge.pk,
    )


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def wallet_challenge_view(request, challenge_id: int):
    challenge = get_object_or_404(
        WalletLinkChallenge,
        pk=challenge_id,
        user=request.user,
    )
    form = WalletSignatureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            verify_wallet_link_challenge(
                request.user,
                challenge.pk,
                form.cleaned_data["signature"],
            )
        except ValidationError as exc:
            form.add_error("signature", exc)
        else:
            return redirect("accounts:wallets")
    return render(
        request,
        "accounts/wallet_challenge.html",
        {"challenge": challenge, "form": form},
        status=400 if request.method == "POST" and form.errors else 200,
    )


@never_cache
@login_required
@require_POST
def unlink_wallet_view(request, wallet_id: int):
    try:
        unlink_wallet(request.user, wallet_id)
    except ValidationError as exc:
        return render(
            request,
            "accounts/wallets.html",
            _wallets_context(request.user, error=exc),
            status=400,
        )
    return redirect("accounts:wallets")


def _payout_addresses_context(user, form=None, error=None) -> dict[str, object]:
    return {
        "form": form or PayoutAddressForm(),
        "payout_addresses": PayoutAddress.objects.filter(user=user),
        "error": error,
        "now": timezone.now(),
    }


@never_cache
@login_required
@require_http_methods(["GET"])
def payout_addresses_view(request):
    return render(
        request,
        "accounts/payout_addresses.html",
        _payout_addresses_context(request.user),
    )


@never_cache
@login_required
@require_POST
def payout_address_save_view(request):
    form = PayoutAddressForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "accounts/payout_addresses.html",
            _payout_addresses_context(request.user, form=form),
            status=400,
        )
    try:
        save_payout_address(
            request.user,
            form.cleaned_data["chain"],
            form.cleaned_data["address"],
            form.cleaned_data["address_confirmation"],
            form.cleaned_data["label"],
        )
    except ValidationError as exc:
        form.add_error(None, exc)
        return render(
            request,
            "accounts/payout_addresses.html",
            _payout_addresses_context(request.user, form=form),
            status=400,
        )
    return redirect("accounts:payout_addresses")


@never_cache
@login_required
@require_POST
def payout_address_delete_view(request, payout_address_id: int):
    try:
        delete_payout_address(request.user, payout_address_id)
    except ValidationError as exc:
        return render(
            request,
            "accounts/payout_addresses.html",
            _payout_addresses_context(request.user, error=exc),
            status=400,
        )
    return redirect("accounts:payout_addresses")


@never_cache
@login_required
@require_POST
def payout_address_verify_start_view(request, payout_address_id: int):
    try:
        challenge = create_payout_address_challenge(
            request.user,
            payout_address_id,
        )
    except ValidationError as exc:
        return render(
            request,
            "accounts/payout_addresses.html",
            _payout_addresses_context(request.user, error=exc),
            status=400,
        )
    return redirect(
        "accounts:payout_address_verify",
        challenge_id=challenge.pk,
    )


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def payout_address_verify_view(request, challenge_id: int):
    challenge = get_object_or_404(
        PayoutAddressChallenge.objects.select_related("payout_address"),
        pk=challenge_id,
        user=request.user,
    )
    form = WalletSignatureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            verify_payout_address_challenge(
                request.user,
                challenge.pk,
                form.cleaned_data["signature"],
            )
        except ValidationError as exc:
            form.add_error("signature", exc)
        else:
            return redirect("accounts:payout_addresses")
    return render(
        request,
        "accounts/payout_address_verify.html",
        {"challenge": challenge, "form": form},
        status=400 if request.method == "POST" and form.errors else 200,
    )


@login_required
@require_POST
def regenerate_recovery_codes_view(request):
    _begin_pgp_flow(request, request.user, "regenerate")
    return redirect("accounts:pgp_auth")
