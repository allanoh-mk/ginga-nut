from django.urls import path

from catalog import views

app_name = "catalog"

urlpatterns = [
    path("", views.category_list, name="categories"),
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/<int:listing_id>/", views.cart_add, name="cart_add"),
    path("cart/update/", views.cart_update, name="cart_update"),
    path("checkout/confirm/", views.cart_checkout_confirm, name="cart_checkout"),
    path("order-created/", views.order_created, name="order_created"),
    path("search/", views.catalog_search, name="search"),
    path("categories/<slug:slug>/", views.category_detail, name="category"),
    path("listings/<int:listing_id>/", views.listing_detail, name="listing"),
    path(
        "listings/<int:listing_id>/reviews/",
        views.listing_reviews,
        name="listing-reviews",
    ),
    path(
        "listings/<int:listing_id>/checkout/",
        views.checkout_view,
        name="checkout",
    ),
    path("vendor/", views.vendor_dashboard, name="vendor-dashboard"),
    path("vendor/bond/", views.vendor_bond, name="vendor-bond"),
    path("vendor/orders/", views.vendor_order_queue, name="vendor-order-queue"),
    path("vendor/payouts/", views.vendor_payouts, name="vendor-payouts"),
    path("vendor/listings/new/", views.listing_create, name="vendor-create-listing"),
    path(
        "vendor/listings/<int:listing_id>/edit/",
        views.listing_edit,
        name="vendor-edit-listing",
    ),
    path(
        "vendor/listings/<int:listing_id>/delete/",
        views.listing_delete,
        name="vendor-delete-listing",
    ),
    path("admin/vendors/", views.vendor_approval_queue, name="vendor-approval-queue"),
    path("admin/makers/", views.maker_approval_queue, name="maker-approval-queue"),
    path(
        "admin/makers/<int:listing_id>/approve/",
        views.maker_approve,
        name="maker-approve",
    ),
    path(
        "vendors/<str:username>/",
        views.vendor_public_profile,
        name="vendor-public-profile",
    ),
    path(
        "admin/vendors/<int:profile_id>/approve/",
        views.vendor_approve,
        name="vendor-approve",
    ),
]
