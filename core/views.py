from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.models import Notification


@require_GET
def home(request):
    from catalog.models import Category

    categories = Category.objects.annotate(
        active_listing_count=Count(
            "listings",
            filter=Q(
                listings__is_active=True,
                listings__is_approved=True,
                listings__vendor__is_approved=True,
                listings__shipping_required=True,
                listings__stock__gt=0,
            ),
        )
    ).order_by("name")[:3]
    return render(request, "public/home.html", {"categories": categories})


@require_GET
def how_it_works(request):
    return render(request, "public/how_it_works.html")


@require_GET
def styleguide(request):
    return render(
        request,
        "styleguide.html",
        {
            "table_headings": ["Order", "Amount", "State"],
            "table_rows": [
                ["#KM-2048", "12,500 base units", "Funded"],
                ["#KM-2047", "8,250 base units", "Finalized"],
            ],
            "empty_rows": [],
        },
    )


def paused_new_orders(request):
    return render(request, "paused/new_orders.html", status=503)


def paused_withdrawals(request):
    return render(request, "paused/withdrawals.html", status=503)


def paused_digital_listings(request):
    return render(request, "paused/digital_listings.html", status=503)


def error_400(request):
    return render(request, "400.html", status=400)


def error_403(request):
    return render(request, "403.html", status=403)


def error_404(request):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)


@login_required
@require_GET
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user)
    page_obj = Paginator(notifications, 25).get_page(request.GET.get("page"))
    icons = {
        Notification.Type.ORDER_FUNDED: "₿",
        Notification.Type.ORDER_ACCEPTED: "✓",
        Notification.Type.ORDER_REJECTED: "!",
        Notification.Type.ORDER_PACKED: "□",
        Notification.Type.ORDER_DISPATCHED: "→",
        Notification.Type.ORDER_DELIVERED: "✓",
        Notification.Type.ORDER_FINALIZED: "★",
        Notification.Type.ORDER_CANCELLED: "×",
        Notification.Type.ORDER_EXPIRED: "!",
        Notification.Type.ORDER_REFUNDED: "↩",
        Notification.Type.SETTLEMENT_PENDING: "…",
        Notification.Type.SETTLEMENT_COMPLETED: "✓",
        Notification.Type.DISPUTE_OPENED: "⚑",
        Notification.Type.DISPUTE_RULING: "§",
        Notification.Type.WITHDRAWAL_APPROVED: "✓",
        Notification.Type.WITHDRAWAL_SENT: "→",
        Notification.Type.VENDOR_APPROVED: "✓",
        Notification.Type.LISTING_APPROVED: "✓",
    }
    for notification in page_obj:
        notification.icon = icons.get(notification.type, "•")
    return render(
        request,
        "core/notifications.html",
        {
            "notifications": page_obj,
            "page_obj": page_obj,
        },
    )


@login_required
@require_GET
def open_notification(request, notification_id: int):
    notification = get_object_or_404(
        Notification,
        pk=notification_id,
        recipient=request.user,
    )
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=("read_at",))
    data = notification.data if isinstance(notification.data, dict) else {}
    destination = reverse("core:notifications")

    order_id = data.get("order_id")
    if isinstance(order_id, int) and not isinstance(order_id, bool):
        destination = reverse("orders:detail", args=(order_id,))
    dispute_id = data.get("dispute_id")
    if (
        notification.type == Notification.Type.DISPUTE_RULING
        and request.user.is_staff
        and isinstance(dispute_id, int)
        and not isinstance(dispute_id, bool)
    ):
        destination = reverse("orders:review-dispute", args=(dispute_id,))
    withdrawal_id = data.get("withdrawal_id")
    if isinstance(withdrawal_id, int) and not isinstance(withdrawal_id, bool):
        destination = reverse("accounts:withdrawal_detail", args=(withdrawal_id,))
    if notification.type == Notification.Type.VENDOR_APPROVED:
        destination = reverse("catalog:vendor-dashboard")
    listing_id = data.get("listing_id")
    if isinstance(listing_id, int) and not isinstance(listing_id, bool):
        destination = reverse("catalog:listing", args=(listing_id,))
    return redirect(destination)


@login_required
@require_POST
def mark_notifications_read(request):
    Notification.objects.filter(
        recipient=request.user,
        read_at__isnull=True,
    ).update(read_at=timezone.now())
    return redirect("core:notifications")
