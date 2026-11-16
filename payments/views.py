import json

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.services.monero_order_escrow import (
    apply_monero_escrow_callback,
    verify_monero_escrow_callback,
)
from payments.models import MoneroOrderEscrow


@csrf_exempt
@require_POST
def monero_escrow_callback(request):
    if len(request.body) > 64 * 1024:
        return HttpResponse(status=413)
    if request.content_type != "application/json":
        return HttpResponse(status=415)
    timestamp = request.headers.get("X-Kola-Timestamp", "")
    nonce = request.headers.get("X-Kola-Nonce", "")
    signature = request.headers.get("X-Kola-Signature", "")
    if not verify_monero_escrow_callback(
        request.body,
        timestamp,
        nonce,
        signature,
    ):
        return HttpResponse(status=401)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            return JsonResponse({"error": "invalid_payload"}, status=400)
        apply_monero_escrow_callback(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "invalid_json"}, status=400)
    except MoneroOrderEscrow.DoesNotExist:
        return JsonResponse({"error": "unknown_escrow"}, status=404)
    except ValidationError:
        return JsonResponse({"error": "invalid_event"}, status=400)

    escrow = MoneroOrderEscrow.objects.get(order_id=payload["order_id"])
    return JsonResponse(
        {
            "accepted": True,
            "state": escrow.state,
            "amount_atomic": escrow.expected_amount_atomic,
            "base_units_per_coin": (
                escrow.rate_quote.base_units_per_coin if escrow.rate_quote_id else None
            ),
            "quote_expires_at": (
                escrow.rate_quote.locked_until.isoformat()
                if escrow.rate_quote_id
                else None
            ),
        }
    )
