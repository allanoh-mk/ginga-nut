from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from catalog.models import Category
from core.services.accept import accept
from core.services.cancel_order import cancel_order
from core.services.dispatch_order import dispatch_order
from core.services.extend_finalize import extend_finalize
from core.services.fund_order import fund_order
from core.services.monero_order_escrow import start_monero_order_escrow
from core.services.open_dispute import open_dispute
from core.services.order_transitions import ORDER_TRANSITIONS
from core.services.pack_order import pack_order
from core.services.record_delivery import record_delivery
from core.services.reject import reject
from core.services.rule_dispute import rule_dispute
from core.services.submit_dispute_evidence import submit_dispute_evidence
from core.services.submit_review import submit_review
from ledger.exceptions import InsufficientFunds
from orders.forms import (
    DispatchOrderForm,
    DisputeEvidenceForm,
    OpenDisputeForm,
    PackOrderForm,
    ProofOfDeliveryForm,
    PublicRulingForm,
    ReviewForm,
)
from orders.models import Dispute, DisputeEvidence, Order, PublicRuling


def _is_participant(order: Order, user) -> bool:
    return order.buyer_id == user.pk or (
        order.vendor_id is not None and order.vendor.user_id == user.pk
    )


@login_required
@require_GET
@never_cache
def order_detail(request, order_id: int):
    orders = Order.objects.select_related(
        "buyer",
        "vendor__user",
        "delivery_zone__city",
        "monero_escrow__rate_quote",
        "review",
    )
    if request.user.is_staff:
        orders = orders.prefetch_related("staff_transition_logs__actor")
    order = get_object_or_404(orders, pk=order_id)
    staff_view = request.user.is_staff
    if not staff_view and not _is_participant(order, request.user):
        raise PermissionDenied

    pod_token = (
        None if staff_view else request.session.pop(f"pod-token:{order.pk}", None)
    )
    allowed_actions = (
        {action for (state, action) in ORDER_TRANSITIONS if state == order.state}
        if not staff_view
        else set()
    )
    staff_transition_targets = (
        [Order.State.ACCEPTED]
        if staff_view and order.state == Order.State.FUNDED
        else []
    )
    return render(
        request,
        "orders/detail.html",
        {
            "order": order,
            "pod_token": pod_token,
            "evidence_choices": Dispute.EvidenceKind.choices,
            "allowed_actions": allowed_actions,
            "transitions": allowed_actions,
            "staff_view": staff_view,
            "staff_transition_targets": staff_transition_targets,
            "staff_transition_logs": (
                order.staff_transition_logs.all() if staff_view else ()
            ),
            "review_form": (
                ReviewForm()
                if (
                    not staff_view
                    and request.user.pk == order.buyer_id
                    and order.state == Order.State.FINALIZED
                    and not hasattr(order, "review")
                )
                else None
            ),
        },
    )


@login_required
@require_POST
def submit_review_view(request, order_id: int):
    order = get_object_or_404(
        Order.objects.select_related(
            "buyer",
            "vendor__user",
            "listing",
            "review",
        ),
        pk=order_id,
    )
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return _render_review_error(request, order, form, status=400)
    try:
        submit_review(
            order_id,
            request.user,
            form.cleaned_data["rating"],
            form.cleaned_data["comment"],
        )
    except ValidationError as exc:
        form.add_error(None, exc)
        return _render_review_error(request, order, form, status=400)
    return redirect("orders:detail", order_id=order.pk)


def _render_review_error(request, order: Order, form: ReviewForm, *, status: int):
    if not _is_participant(order, request.user):
        raise PermissionDenied
    allowed_actions = {
        action for (state, action) in ORDER_TRANSITIONS if state == order.state
    }
    return render(
        request,
        "orders/detail.html",
        {
            "order": order,
            "pod_token": None,
            "evidence_choices": Dispute.EvidenceKind.choices,
            "allowed_actions": allowed_actions,
            "transitions": allowed_actions,
            "review_form": None if hasattr(order, "review") else form,
        },
        status=status,
    )


@login_required
@require_GET
def order_history(request):
    orders = (
        Order.objects.filter(Q(buyer=request.user) | Q(vendor__user=request.user))
        .select_related("buyer", "vendor__user", "listing")
        .order_by("-created_at", "-pk")
    )
    page_obj = Paginator(orders, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/history.html",
        {"orders": page_obj, "page_obj": page_obj},
    )


@login_required
@require_POST
def pack_order_view(request, order_id: int):
    form = PackOrderForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "orders/action_error.html",
            {"form": form},
            status=400,
        )
    try:
        pack_order(order_id, request.user, form.cleaned_data["photo"])
    except (PermissionDenied, ValidationError) as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400 if isinstance(exc, ValidationError) else 403,
        )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def dispatch_order_view(request, order_id: int):
    form = DispatchOrderForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "orders/action_error.html",
            {"form": form},
            status=400,
        )
    try:
        _, token = dispatch_order(
            order_id,
            request.user,
            form.cleaned_data["courier_reference"],
        )
    except (PermissionDenied, ValidationError) as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400 if isinstance(exc, ValidationError) else 403,
        )
    request.session[f"pod-token:{order_id}"] = token
    return redirect("orders:detail", order_id=order_id)


@require_POST
def record_delivery_view(request, order_id: int):
    form = ProofOfDeliveryForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "orders/action_error.html",
            {"form": form},
            status=400,
        )
    try:
        record_delivery(order_id, form.cleaned_data["token"])
    except (PermissionDenied, ValidationError) as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400 if isinstance(exc, ValidationError) else 403,
        )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def open_dispute_view(request, order_id: int):
    form = OpenDisputeForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "orders/action_error.html",
            {"form": form},
            status=400,
        )
    try:
        dispute = open_dispute(
            order_id=order_id,
            actor=request.user,
            reason=form.cleaned_data["reason"],
            evidence_kind=form.cleaned_data["evidence_kind"],
            attachment=form.cleaned_data["attachment"],
            description=form.cleaned_data["description"],
        )
    except (PermissionDenied, ValidationError) as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400 if isinstance(exc, ValidationError) else 403,
        )
    return redirect("orders:detail", order_id=dispute.order_id)


@login_required
@require_POST
def submit_dispute_evidence_view(request, dispute_id: int):
    form = DisputeEvidenceForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            "orders/action_error.html",
            {"form": form},
            status=400,
        )
    try:
        evidence = submit_dispute_evidence(
            dispute_id=dispute_id,
            actor=request.user,
            kind=form.cleaned_data["kind"],
            attachment=form.cleaned_data["attachment"],
            description=form.cleaned_data["description"],
        )
    except (PermissionDenied, ValidationError) as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400 if isinstance(exc, ValidationError) else 403,
        )
    return redirect("orders:detail", order_id=evidence.dispute.order_id)


@staff_member_required
@require_GET
@never_cache
def dispute_queue(request):
    disputes = (
        Dispute.objects.filter(
            order__state=Order.State.DISPUTED,
            public_ruling__isnull=True,
        )
        .select_related("order")
        .order_by("created_at", "pk")
    )
    page_obj = Paginator(disputes, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/dispute_queue.html",
        {"disputes": page_obj, "page_obj": page_obj},
    )


@staff_member_required
@never_cache
def review_dispute(request, dispute_id: int):
    dispute = get_object_or_404(
        Dispute.objects.select_related("order", "order__listing__category"),
        pk=dispute_id,
    )
    existing_ruling = getattr(dispute, "public_ruling", None)
    form = PublicRulingForm(request.POST or None)
    form.fields["category"].queryset = Category.objects.filter(
        pk=dispute.order.listing.category_id
    )
    if request.method == "POST" and form.is_valid():
        try:
            rule_dispute(
                dispute_id=dispute.pk,
                actor=request.user,
                amount_band=form.cleaned_data["amount_band"],
                category=form.cleaned_data["category"],
                outcome=form.cleaned_data["outcome"],
                reason=form.cleaned_data["reason"],
                released_amount_base_units=form.cleaned_data[
                    "released_amount_base_units"
                ],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("orders:review-dispute", dispute_id=dispute.pk)
    return render(
        request,
        "orders/review_dispute.html",
        {
            "dispute": dispute,
            "evidence": dispute.evidence.select_related("submitted_by").all(),
            "form": form,
            "existing_ruling": existing_ruling,
            "evidence_choices": Dispute.EvidenceKind.choices,
        },
    )


@staff_member_required
@require_GET
@never_cache
def evidence_download(request, evidence_id: int):
    evidence = get_object_or_404(DisputeEvidence, pk=evidence_id)
    return FileResponse(
        evidence.attachment.open("rb"),
        as_attachment=True,
        filename=evidence.attachment.name.rsplit("/", 1)[-1],
    )


@require_GET
def public_rulings(request):
    rulings = PublicRuling.objects.select_related("category").order_by(
        "-created_at",
        "-pk",
    )
    page_obj = Paginator(rulings, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/public_rulings.html",
        {"rulings": page_obj, "page_obj": page_obj},
    )


@require_GET
def public_ruling_detail(request, ruling_id: int):
    ruling = get_object_or_404(
        PublicRuling.objects.select_related("category"),
        pk=ruling_id,
    )
    return render(request, "orders/public_ruling_detail.html", {"ruling": ruling})


@login_required
@require_POST
def fund_order_view(request, order_id: int):
    try:
        fund_order(order_id, request.user)
    except InsufficientFunds as exc:
        return render(
            request,
            "orders/action_error.html",
            {
                "message": "The balance is too low to fund this order.",
                "insufficient_balance": True,
                "detail": str(exc),
            },
            status=400,
        )
    except ValidationError as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400,
        )
    except PermissionDenied as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=403,
        )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def start_monero_escrow_view(request, order_id: int):
    try:
        start_monero_order_escrow(order_id, request.user)
    except PermissionDenied as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=403,
        )
    except ValidationError as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400,
        )
    except ImproperlyConfigured as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=503,
        )
    messages.info(
        request,
        "Monero multisig setup requested. The deposit address will appear after the independent signers prepare the escrow.",
    )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def cancel_order_view(request, order_id: int):
    try:
        cancel_order(order_id, request.user)
    except ValidationError as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400,
        )
    except PermissionDenied as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=403,
        )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def accept_order_view(request, order_id: int):
    try:
        accept(order_id, request.user)
    except ValidationError as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400,
        )
    except PermissionDenied as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=403,
        )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def reject_order_view(request, order_id: int):
    try:
        reject(order_id, request.user)
    except ValidationError as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400,
        )
    except PermissionDenied as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=403,
        )
    return redirect("orders:detail", order_id=order_id)


@login_required
@require_POST
def extend_finalize_view(request, order_id: int):
    try:
        extend_finalize(order_id, request.user)
    except ValidationError as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=400,
        )
    except PermissionDenied as exc:
        return render(
            request,
            "orders/action_error.html",
            {"message": str(exc)},
            status=403,
        )
    return redirect("orders:detail", order_id=order_id)
