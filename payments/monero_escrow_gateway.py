import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote, urlparse

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from payments.providers.base import ProviderError

_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 64 * 1024


def gateway_configuration() -> tuple[str, bytes]:
    url = settings.MONERO_ESCROW_GATEWAY_URL
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in {None, 443}
        or parsed.hostname not in settings.MONERO_ESCROW_GATEWAY_ALLOWED_HOSTS
    ):
        raise ImproperlyConfigured(
            "Monero escrow gateway must use HTTPS and an explicitly allowlisted host."
        )
    secret = settings.MONERO_ESCROW_GATEWAY_SECRET
    if len(secret) < 32:
        raise ImproperlyConfigured(
            "MONERO_ESCROW_GATEWAY_SECRET must contain at least 32 characters."
        )
    return url, secret.encode("utf-8")


def _request(method: str, path: str, payload: dict, idempotency_key: str) -> dict:
    base_url, secret = gateway_configuration()
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    timestamp = str(time.time_ns() // 1_000_000_000)
    nonce = secrets.token_urlsafe(24)
    signed_message = b".".join((timestamp.encode(), nonce.encode(), body))
    signature = hmac.new(secret, signed_message, hashlib.sha256).hexdigest()
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.request(
            method,
            f"{base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Kola-Timestamp": timestamp,
                "X-Kola-Nonce": nonce,
                "X-Kola-Signature": signature,
                "Idempotency-Key": idempotency_key,
            },
            timeout=_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ProviderError("Monero escrow gateway response is too large.")
        result = response.json()
    except requests.RequestException as error:
        raise ProviderError("Monero escrow gateway request failed.") from error
    except ValueError as error:
        raise ProviderError("Monero escrow gateway returned invalid JSON.") from error
    finally:
        session.close()
    if not isinstance(result, dict):
        raise ProviderError("Monero escrow gateway returned an invalid response.")
    return result


def create_remote_escrow(*, order, callback_url: str) -> str:
    if not callback_url:
        raise ImproperlyConfigured(
            "MONERO_ESCROW_CALLBACK_URL is required for multisig escrow."
        )
    payload = {
        "order_id": order.pk,
        "buyer_id": order.buyer_id,
        "vendor_user_id": order.vendor.user_id,
        "amount_base_units": order.total_amount,
        "release_address": settings.MONERO_ESCROW_RELEASE_ADDRESS,
        "callback_url": callback_url,
        "protocol_version": 1,
        "signing_policy": {
            "participants": ["buyer", "vendor", "mediator"],
            "threshold": 2,
            "mediator_alone_must_not_sign": True,
            "participant_authorization_required_for_settlement": True,
        },
    }
    if not payload["release_address"]:
        raise ImproperlyConfigured(
            "MONERO_ESCROW_RELEASE_ADDRESS is required for multisig escrow."
        )
    result = _request(
        "POST",
        "/v1/escrows",
        payload,
        f"order-{order.pk}-escrow-create",
    )
    remote_id = result.get("escrow_id")
    if not isinstance(remote_id, str) or not remote_id or len(remote_id) > 128:
        raise ProviderError("Monero escrow gateway returned an invalid escrow ID.")
    return remote_id


def request_remote_settlement(*, escrow, order) -> None:
    if not escrow.external_id:
        raise ProviderError("Monero escrow has not been initialized by the gateway.")
    result = _request(
        "POST",
        f"/v1/escrows/{quote(escrow.external_id, safe='')}/settlements",
        {
            "action": escrow.settlement_action,
            "release_base_units": escrow.settlement_release_base_units or 0,
            "order_id": order.pk,
            "protocol_version": 1,
        },
        (
            f"order-{order.pk}-settlement-"
            f"{escrow.settlement_action}-{escrow.last_event_sequence}"
        ),
    )
    if result.get("status") != "pending_participant_approval":
        raise ProviderError(
            "Monero escrow gateway did not create an approval-gated settlement."
        )


def request_remote_cancel(*, escrow, order) -> None:
    if not escrow.external_id:
        raise ProviderError("Monero escrow has not been initialized by the gateway.")
    result = _request(
        "POST",
        f"/v1/escrows/{quote(escrow.external_id, safe='')}/cancel",
        {
            "order_id": order.pk,
            "reason": escrow.cancellation_reason,
            "protocol_version": 1,
        },
        f"order-{order.pk}-escrow-cancel-{escrow.cancellation_reason}",
    )
    if result.get("status") not in {"cancel_pending", "refund_required"}:
        raise ProviderError("Monero escrow gateway returned an invalid cancel status.")


def multisig_escrow_balance_atomic() -> int:
    result = _request(
        "GET",
        "/v1/reserves/xmr",
        {},
        "kola-xmr-multisig-reserve-balance",
    )
    amount = result.get("confirmed_balance_atomic")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ProviderError(
            "Monero escrow gateway returned an invalid reserve balance."
        )
    return amount
