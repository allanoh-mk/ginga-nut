from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from redis import Redis
from redis.exceptions import RedisError

from core.jobs import FINANCIAL_JOB_QUEUE
from core.services.approve_withdrawal import approve_withdrawal
from core.services.force_order_transition import force_order_transition
from core.services.get_ops_dashboard_metrics import get_ops_dashboard_metrics
from core.services.is_market_feature_enabled import FEATURE_FIELDS
from core.services.reject_withdrawal import reject_withdrawal
from core.services.set_market_feature import set_market_feature
from core.services.sign_canary_statement import sign_canary_statement
from ops.forms import OrderFilterForm
from ops.models import ReserveIntegrityRun, ReserveSnapshot
from orders.models import Order
from payments.models import Withdrawal


@require_GET
def reserve_history(request):
    snapshots = ReserveSnapshot.objects.all()
    latest = snapshots.first()
    latest_integrity = ReserveIntegrityRun.objects.first()
    history = Paginator(snapshots, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "ops/reserve_history.html",
        {
            "latest": latest,
            "latest_integrity": latest_integrity,
            "history": history,
        },
    )


@staff_member_required
@require_GET
def admin_dashboard(request):
    return render(
        request,
        "ops/admin_dashboard.html",
        get_ops_dashboard_metrics(),
    )


@staff_member_required
@require_GET
def order_list(request):
    form = OrderFilterForm(request.GET or None)
    orders = Order.objects.select_related(
        "buyer",
        "vendor__user",
        "listing",
        "delivery_zone__city",
    )
    if form.is_valid():
        filters = form.cleaned_data
        if filters["status"]:
            orders = orders.filter(state=filters["status"])
        if filters["city"]:
            orders = orders.filter(delivery_zone__city=filters["city"])
        if filters["start_date"]:
            orders = orders.filter(created_at__date__gte=filters["start_date"])
        if filters["end_date"]:
            orders = orders.filter(created_at__date__lte=filters["end_date"])
    page_obj = Paginator(orders.order_by("-created_at", "-pk"), 25).get_page(
        request.GET.get("page")
    )
    pagination_query = request.GET.copy()
    pagination_query.pop("page", None)
    return render(
        request,
        "ops/order_list.html",
        {
            "form": form,
            "page_obj": page_obj,
            "pagination_query": pagination_query.urlencode(),
        },
    )


@staff_member_required
@require_POST
def order_force_transition(request, order_id: int):
    order = get_object_or_404(Order, pk=order_id)
    try:
        force_order_transition(
            order.pk,
            request.POST.get("target_state", ""),
            request.user,
            request.POST.get("reason", ""),
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, f"Order {order.pk} transition recorded.")
    return redirect("orders:detail", order_id=order.pk)


@staff_member_required
@require_POST
def market_switch_toggle(request, feature: str):
    if feature not in FEATURE_FIELDS:
        messages.error(request, "Unknown market feature.")
        return redirect("ops:dashboard")
    reason = request.POST.get("reason", "")
    if not reason.strip():
        messages.error(request, "A reason is required.")
        return redirect("ops:dashboard")
    try:
        set_market_feature(
            feature,
            None,
            actor=request.user,
            reason=reason,
        )
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request, f"{feature.replace('_', ' ').title()} setting updated."
        )
    return redirect("ops:dashboard")


@staff_member_required
@require_GET
def withdrawal_approval_queue(request):
    withdrawals = (
        Withdrawal.objects.filter(state=Withdrawal.State.MANUAL_APPROVAL)
        .select_related("user")
        .order_by("created_at", "pk")
    )
    page = Paginator(withdrawals, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "ops/withdrawal_approval.html",
        {"page_obj": page},
    )


@staff_member_required
@require_POST
def withdrawal_approve(request, withdrawal_id: int):
    withdrawal = get_object_or_404(
        Withdrawal,
        pk=withdrawal_id,
        state=Withdrawal.State.MANUAL_APPROVAL,
    )
    try:
        approve_withdrawal(withdrawal, request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Withdrawal {withdrawal.pk} approved and queued for processing.",
        )
    return redirect("ops:withdrawal-approval-queue")


@staff_member_required
@require_POST
def withdrawal_reject(request, withdrawal_id: int):
    withdrawal = get_object_or_404(
        Withdrawal,
        pk=withdrawal_id,
        state=Withdrawal.State.MANUAL_APPROVAL,
    )
    try:
        reject_withdrawal(
            withdrawal,
            request.user,
            request.POST.get("reason", ""),
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Withdrawal {withdrawal.pk} rejected and the reserve returned.",
        )
    return redirect("ops:withdrawal-approval-queue")


@require_GET
def public_canary(request):
    canary = sign_canary_statement()
    return render(
        request,
        "ops/canary.html",
        {"canary": canary, "signed_at": timezone.now() if canary else None},
    )


@require_GET
def health(request):
    unhealthy = []
    postgres_stats = None
    pool_stats = {
        "available": False,
        "reason": "No PostgreSQL connection pool is configured.",
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE state = 'active') AS active,
                    COUNT(*) FILTER (WHERE state = 'idle') AS idle,
                    current_setting('max_connections')::integer AS max_connections
                FROM pg_stat_activity
                """
            )
            total, active, idle, max_connections = cursor.fetchone()
        postgres_stats = {
            "total_connections": total,
            "active_connections": active,
            "idle_connections": idle,
            "max_connections": max_connections,
            "connection_max_age_seconds": connection.settings_dict.get(
                "CONN_MAX_AGE", 0
            ),
        }
    except DatabaseError:
        unhealthy.append("database")

    client = Redis.from_url(settings.QUEUE_REDIS_URL, decode_responses=True)
    queue_depth = None
    try:
        client.ping()
        observed_depth = client.zcard(FINANCIAL_JOB_QUEUE)
        queue_depth = observed_depth if isinstance(observed_depth, int) else None
    except RedisError:
        unhealthy.append("redis")
    finally:
        client.close()

    status_code = 503 if unhealthy else 200
    return JsonResponse(
        {
            "status": "unhealthy" if unhealthy else "ok",
            "unhealthy": unhealthy,
            "scheduler": {
                "last_run_at": None,
                "available": False,
                "source": "No durable scheduler run record is available.",
            },
            "deposit_poll": {
                "last_run_at": None,
                "available": False,
                "source": "Deposit records track observations, not poll-run timestamps.",
            },
            "redis": {
                "healthy": "redis" not in unhealthy,
                "financial_queue_depth": queue_depth,
            },
            "postgres": {
                "healthy": "database" not in unhealthy,
                "connections": postgres_stats,
                "pool": pool_stats,
            },
        },
        status=status_code,
    )


@staff_member_required
@require_GET
def health_page(request):
    checks = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks.append(("PostgreSQL", True, "Database query completed."))
    except DatabaseError:
        checks.append(("PostgreSQL", False, "Database query failed."))
    client = Redis.from_url(settings.QUEUE_REDIS_URL, decode_responses=True)
    try:
        client.ping()
        checks.append(("Redis", True, "Queue service responded."))
    except RedisError:
        checks.append(("Redis", False, "Queue service did not respond."))
    finally:
        client.close()
    return render(
        request,
        "ops/health.html",
        {"checks": checks, "healthy": all(item[1] for item in checks)},
    )
