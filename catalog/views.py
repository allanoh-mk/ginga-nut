from uuid import uuid4

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from catalog.exceptions import InsufficientStock, ListingUnavailable
from catalog.forms import (
    CartCheckoutForm,
    CatalogSearchForm,
    CheckoutForm,
    ListingForm,
    VendorListingFilterForm,
)
from catalog.models import Category, Listing, Review, VendorProfile
from core.services.approve_vendor import approve_vendor
from core.services.create_order import create_order
from core.services.create_vendor_profile import create_vendor_profile
from core.services.delete_listing import delete_listing
from core.services.get_available_balance import get_available_balance
from core.services.get_ledger_account import get_ledger_account
from core.services.order_deadlines import FUNDED_VENDOR_RESPONSE_LIFETIME
from core.services.post_transfer import post_transfer
from core.services.save_listing import save_listing
from ledger.exceptions import InsufficientFunds
from orders.forms import DispatchOrderForm, PackOrderForm
from orders.models import Order
from payments.models import Withdrawal

CART_SESSION_KEY = "market_cart"


def _cart(request):
    stored = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(stored, dict):
        stored = {}
    ids = []
    quantities = {}
    for raw_id, raw_quantity in stored.items():
        try:
            listing_id, quantity = int(raw_id), int(raw_quantity)
        except (TypeError, ValueError):
            continue
        if listing_id > 0 and quantity > 0:
            ids.append(listing_id)
            quantities[listing_id] = quantity
    listings = Listing.objects.filter(
        pk__in=ids,
        is_active=True,
        is_approved=True,
        vendor__is_approved=True,
        shipping_required=True,
    ).select_related("category", "vendor__user", "delivery_zone__city")
    items = []
    for listing in listings:
        quantity = min(quantities[listing.pk], listing.stock)
        if quantity:
            items.append(
                {
                    "listing": listing,
                    "quantity": quantity,
                    "subtotal": listing.price * quantity,
                }
            )
    order_map = {str(item["listing"].pk): item["quantity"] for item in items}
    if order_map != stored:
        request.session[CART_SESSION_KEY] = order_map
    groups = {}
    for item in items:
        vendor = item["listing"].vendor
        group = groups.setdefault(
            vendor.pk, {"vendor": vendor, "items": [], "subtotal": 0}
        )
        group["items"].append(item)
        group["subtotal"] += item["subtotal"]
    return items, list(groups.values()), sum(item["subtotal"] for item in items)


def category_list(request):
    categories = Category.objects.filter(
        listings__is_active=True,
        listings__is_approved=True,
        listings__vendor__is_approved=True,
        listings__shipping_required=True,
    ).distinct()
    return render(
        request,
        "catalog/category_list.html",
        {
            "categories": categories,
            "search_form": CatalogSearchForm(),
        },
    )


@require_http_methods(["GET", "POST"])
def cart_view(request):
    items, groups, total = _cart(request)
    return render(
        request,
        "catalog/cart.html",
        {
            "items": items,
            "vendor_groups": groups,
            "total": total,
            "error": request.GET.get("error", ""),
        },
    )


@require_POST
def cart_add(request, listing_id: int):
    listing = get_object_or_404(
        Listing.objects.filter(
            is_active=True,
            is_approved=True,
            vendor__is_approved=True,
            shipping_required=True,
        ),
        pk=listing_id,
    )
    try:
        quantity = int(request.POST.get("quantity", "1"))
    except (TypeError, ValueError):
        quantity = 0
    if quantity < 1 or quantity > listing.stock:
        messages.error(
            request, "The quantity is not available. Choose an in-stock amount."
        )
        return redirect("catalog:listing", listing_id=listing.pk)
    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}
    key = str(listing.pk)
    new_quantity = int(cart.get(key, 0)) + quantity
    if new_quantity > listing.stock:
        messages.error(
            request,
            "The cart quantity exceeds available stock. Reduce the quantity "
            "and try again.",
        )
        return redirect("catalog:listing", listing_id=listing.pk)
    cart[key] = new_quantity
    request.session[CART_SESSION_KEY] = cart
    messages.success(request, "Listing added to cart.")
    return redirect("catalog:cart")


@require_POST
def cart_update(request):
    listing_id = request.POST.get("listing_id", "")
    try:
        listing_id = int(listing_id)
        quantity = int(request.POST.get("quantity", "0"))
    except (TypeError, ValueError):
        messages.error(
            request, "The cart quantity is invalid. Enter a whole number and try again."
        )
        return redirect("catalog:cart")
    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}
    key = str(listing_id)
    if quantity <= 0:
        cart.pop(key, None)
    else:
        listing = Listing.objects.filter(
            pk=listing_id,
            is_active=True,
            is_approved=True,
            vendor__is_approved=True,
            shipping_required=True,
        ).first()
        if listing is None or quantity > listing.stock:
            messages.error(
                request,
                "The listing is unavailable at that quantity. Update the cart "
                "and try again.",
            )
            return redirect("catalog:cart")
        cart[key] = quantity
    request.session[CART_SESSION_KEY] = cart
    return redirect("catalog:cart")


@login_required
@require_http_methods(["GET", "POST"])
def cart_checkout_confirm(request):
    items, groups, total = _cart(request)
    if not items:
        return render(
            request,
            "catalog/checkout_confirm.html",
            {"items": [], "vendor_groups": [], "total": 0, "form": CartCheckoutForm()},
        )
    form = CartCheckoutForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        created = []
        try:
            with transaction.atomic():
                for item in items:
                    listing = item["listing"]
                    created.append(
                        create_order(
                            buyer=request.user,
                            listing_id=listing.pk,
                            quantity=item["quantity"],
                            shipping_address=form.cleaned_data["shipping_address"],
                            shipping_phone=form.cleaned_data["shipping_phone"],
                            delivery_zone=listing.delivery_zone,
                        )
                    )
        except (InsufficientStock, ListingUnavailable, ValidationError) as exc:
            form.add_error(None, str(exc))
            return render(
                request,
                "catalog/checkout_confirm.html",
                {
                    "items": items,
                    "vendor_groups": groups,
                    "total": total,
                    "form": form,
                    "available_balance": get_available_balance(request.user),
                },
                status=400,
            )
        request.session[CART_SESSION_KEY] = {}
        request.session["order_created_ids"] = [order.pk for order in created]
        return redirect("catalog:order_created")
    return render(
        request,
        "catalog/checkout_confirm.html",
        {
            "items": items,
            "vendor_groups": groups,
            "total": total,
            "form": form,
            "available_balance": get_available_balance(request.user),
        },
        status=400 if request.method == "POST" and form.errors else 200,
    )


@login_required
@require_http_methods(["GET"])
def order_created(request):
    ids = request.session.pop("order_created_ids", [])
    if not isinstance(ids, list) or not ids:
        return redirect("orders:history")
    orders = list(
        Order.objects.filter(pk__in=ids, buyer=request.user)
        .select_related("listing", "vendor__user")
        .order_by("pk")
    )
    if not orders:
        return redirect("orders:history")
    total = sum(order.total_amount for order in orders)
    available_balance = get_available_balance(request.user)
    return render(
        request,
        "catalog/order_created.html",
        {
            "orders": orders,
            "total": total,
            "available_balance": available_balance,
            "insufficient_balance": available_balance < total,
        },
    )


def catalog_search(request):
    form = CatalogSearchForm(request.GET)
    listings = Listing.objects.filter(
        is_active=True,
        is_approved=True,
        vendor__is_approved=True,
        shipping_required=True,
    ).select_related("category", "vendor__user")
    if form.is_valid():
        query = form.cleaned_data["q"].strip()
        category = form.cleaned_data["category"]
        sort = form.cleaned_data["sort"] or "newest"
        if query:
            listings = listings.filter(
                Q(title__icontains=query) | Q(description__icontains=query)
            )
        if category is not None:
            listings = listings.filter(category=category)
        ordering = {
            "price_asc": ("price", "pk"),
            "price_desc": ("-price", "pk"),
            "newest": ("-created_at", "-pk"),
        }[sort]
        listings = listings.order_by(*ordering)
    else:
        listings = listings.none()

    page_obj = Paginator(listings, 25).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "catalog/search_results.html",
        {
            "form": form,
            "listings": page_obj,
            "page_obj": page_obj,
            "pagination_query": query_params.urlencode(),
        },
    )


def category_detail(request, slug: str):
    category = get_object_or_404(Category, slug=slug)
    listings = Listing.objects.filter(
        category=category,
        is_active=True,
        is_approved=True,
        vendor__is_approved=True,
        shipping_required=True,
    ).select_related("category", "vendor__user")
    page_obj = Paginator(listings, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/category_detail.html",
        {"category": category, "listings": page_obj, "page_obj": page_obj},
    )


def listing_detail(request, listing_id: int):
    listing = get_object_or_404(
        Listing.objects.filter(
            is_active=True,
            is_approved=True,
            vendor__is_approved=True,
            shipping_required=True,
        ).select_related("category", "vendor__user"),
        pk=listing_id,
    )
    return render(
        request,
        "catalog/listing_detail.html",
        {"listing": listing, "vendor": listing.vendor},
    )


def listing_reviews(request, listing_id: int):
    listing = get_object_or_404(
        Listing.objects.filter(
            is_active=True,
            is_approved=True,
            vendor__is_approved=True,
            shipping_required=True,
        ).select_related("category"),
        pk=listing_id,
    )
    reviews = Review.objects.filter(order__listing=listing).select_related(
        "order__buyer"
    )
    page_obj = Paginator(reviews, 10).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "catalog/listing_reviews.html",
        {
            "listing": listing,
            "reviews": page_obj,
            "page_obj": page_obj,
            "pagination_query": query_params.urlencode(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def checkout_view(request, listing_id: int):
    listing = get_object_or_404(
        Listing.objects.filter(
            is_active=True,
            is_approved=True,
            vendor__is_approved=True,
            shipping_required=True,
        ).select_related("vendor", "delivery_zone"),
        pk=listing_id,
    )
    form = CheckoutForm(request.POST or None, listing=listing)
    if request.method == "POST" and form.is_valid():
        try:
            order = create_order(
                buyer=request.user,
                listing_id=listing.pk,
                quantity=form.cleaned_data["quantity"],
                shipping_address=form.cleaned_data["shipping_address"],
                shipping_phone=form.cleaned_data["shipping_phone"],
                delivery_zone=form.cleaned_data["delivery_zone"],
            )
        except InsufficientStock as exc:
            form.add_error(None, str(exc))
        except ListingUnavailable:
            form.add_error(None, "This listing is no longer available.")
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Order placed. Fund it to proceed.")
            return redirect("orders:detail", order_id=order.pk)
    return render(
        request,
        "catalog/checkout.html",
        {"form": form, "listing": listing},
    )


@login_required
@require_http_methods(["GET", "POST"])
def vendor_dashboard(request):
    profile = VendorProfile.objects.filter(user=request.user).first()
    if profile is None:
        if request.method == "POST":
            create_vendor_profile(request.user)
            return redirect("catalog:vendor-dashboard")
        return render(request, "catalog/vendor_apply.html")

    form = VendorListingFilterForm(request.GET)
    listings = profile.listings.select_related("category").all()
    if form.is_valid():
        query = form.cleaned_data["q"].strip()
        status = form.cleaned_data["status"]
        if query:
            listings = listings.filter(title__icontains=query)
        if status == "active":
            listings = listings.filter(is_active=True)
        elif status == "inactive":
            listings = listings.filter(is_active=False)
    page_obj = Paginator(listings, 25).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "catalog/vendor_dashboard.html",
        {
            "profile": profile,
            "listings": page_obj,
            "page_obj": page_obj,
            "filter_form": form,
            "pagination_query": query_params.urlencode(),
            "available_balance": get_available_balance(request.user),
        },
    )


@login_required
@require_POST
def vendor_bond(request):
    profile = get_object_or_404(VendorProfile, user=request.user)
    try:
        amount = int(request.POST.get("amount_base_units", ""))
        if amount <= 0:
            raise ValueError
        available = get_ledger_account("user_available", owner=request.user)
        post_transfer(
            available,
            profile.bond_account,
            amount,
            f"vendor-bond-{profile.pk}-{uuid4().hex}",
        )
    except (TypeError, ValueError):
        messages.error(request, "Enter a positive whole amount in base units.")
    except InsufficientFunds:
        messages.error(
            request,
            "Available balance is too low for this bond amount. Add funds "
            "and try again.",
        )
    else:
        messages.success(request, "Vendor bond updated.")
    return redirect("catalog:vendor-dashboard")


@login_required
@require_GET
def vendor_order_queue(request):
    profile = get_object_or_404(VendorProfile, user=request.user)
    now = timezone.now()
    orders = list(
        Order.objects.filter(vendor=profile)
        .exclude(
            state__in=(
                Order.State.FINALIZED,
                Order.State.REFUNDED,
                Order.State.CANCELLED,
                Order.State.EXPIRED,
            )
        )
        .select_related("buyer", "listing")
        .order_by(F("expires_at").asc(nulls_last=True), "created_at", "pk")
    )
    for order in orders:
        if order.state == Order.State.FUNDED and order.funded_at:
            deadline = order.funded_at + FUNDED_VENDOR_RESPONSE_LIFETIME
        else:
            deadline = order.finalize_at or order.expires_at or order.created_at
        order.deadline = deadline
        order.remaining_seconds = max(0, int(((deadline or now) - now).total_seconds()))
        order.can_dispatch = order.state == Order.State.PACKED and bool(
            order.pack_photo
        )
        order.pack_form = (
            PackOrderForm() if order.state == Order.State.ACCEPTED else None
        )
        order.dispatch_form = (
            DispatchOrderForm() if order.state == Order.State.PACKED else None
        )
    orders.sort(key=lambda row: (row.deadline is None, row.deadline or now, row.pk))
    return render(
        request,
        "catalog/vendor_order_queue.html",
        {
            "orders": orders,
        },
    )


@login_required
@require_GET
def vendor_payouts(request):
    profile = get_object_or_404(VendorProfile, user=request.user)
    payouts = Withdrawal.objects.filter(user=request.user).order_by(
        "-created_at", "-pk"
    )
    return render(
        request,
        "catalog/vendor_payouts.html",
        {
            "profile": profile,
            "payouts": Paginator(payouts, 25).get_page(request.GET.get("page")),
        },
    )


@require_GET
def vendor_public_profile(request, username: str):
    profile = get_object_or_404(
        VendorProfile.objects.select_related("user"),
        user__username=username,
        is_approved=True,
    )
    stats = Review.objects.filter(order__vendor=profile).aggregate(
        rating=Avg("rating"), completed=Count("pk")
    )
    listings = profile.listings.filter(
        is_active=True, is_approved=True, shipping_required=True
    ).select_related("category")
    return render(
        request,
        "catalog/vendor_public_profile.html",
        {
            "profile": profile,
            "rating": stats["rating"],
            "completed_count": Order.objects.filter(
                vendor=profile, state=Order.State.FINALIZED
            ).count(),
            "listings": listings,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def listing_create(request):
    form = ListingForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        listing = save_listing(
            actor=request.user, listing_id=None, values=form.cleaned_data
        )
        return redirect("catalog:vendor-edit-listing", listing_id=listing.pk)
    return render(
        request, "catalog/listing_form.html", {"form": form, "title": "New listing"}
    )


@login_required
@require_http_methods(["GET", "POST"])
def listing_edit(request, listing_id: int):
    listing = get_object_or_404(
        Listing.objects.filter(
            vendor__user=request.user,
            vendor__is_approved=True,
        ),
        pk=listing_id,
    )
    form = ListingForm(request.POST or None, request.FILES or None, instance=listing)
    if request.method == "POST" and form.is_valid():
        updated = save_listing(
            actor=request.user,
            listing_id=listing.pk,
            values=form.cleaned_data,
        )
        return redirect("catalog:vendor-edit-listing", listing_id=updated.pk)
    return render(
        request,
        "catalog/listing_form.html",
        {"form": form, "title": "Edit listing", "listing": listing},
    )


@login_required
@require_http_methods(["GET", "POST"])
def listing_delete(request, listing_id: int):
    listing = get_object_or_404(Listing, pk=listing_id, vendor__user=request.user)
    if request.method == "POST":
        delete_listing(actor=request.user, listing_id=listing_id)
        messages.success(request, "Listing deleted.")
        return redirect("catalog:vendor-dashboard")
    return render(request, "catalog/listing_delete.html", {"listing": listing})


@staff_member_required
def vendor_approval_queue(request):
    profiles = (
        VendorProfile.objects.filter(is_approved=False)
        .select_related("user")
        .order_by("created_at", "pk")
    )
    page_obj = Paginator(profiles, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/vendor_approval_queue.html",
        {"profiles": page_obj, "page_obj": page_obj},
    )


@staff_member_required
@require_GET
def maker_approval_queue(request):
    listings = (
        Listing.objects.filter(is_approved=False)
        .select_related("vendor__user", "category")
        .order_by("created_at", "pk")
    )
    page_obj = Paginator(listings, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/maker_approval_queue.html",
        {"listings": page_obj, "page_obj": page_obj},
    )


@staff_member_required
@require_POST
def maker_approve(request, listing_id: int):
    listing = get_object_or_404(Listing, pk=listing_id, is_approved=False)
    listing.is_approved = True
    listing.save(update_fields=("is_approved", "updated_at"))
    messages.success(request, "Listing approved and visible in the catalog.")
    return redirect("catalog:maker-approval-queue")


@staff_member_required
@require_POST
def vendor_approve(request, profile_id: int):
    approve_vendor(profile_id, actor=request.user)
    return redirect("catalog:vendor-approval-queue")
