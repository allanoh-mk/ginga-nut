from django.urls import path

from orders import views

app_name = "orders"

urlpatterns = [
    path("", views.order_history, name="history"),
    path("rulings/", views.public_rulings, name="public-rulings"),
    path("rulings/<int:ruling_id>/", views.public_ruling_detail, name="public-ruling"),
    path("review/", views.dispute_queue, name="dispute-queue"),
    path(
        "review/<int:dispute_id>/",
        views.review_dispute,
        name="review-dispute",
    ),
    path(
        "evidence/<int:evidence_id>/download/",
        views.evidence_download,
        name="evidence-download",
    ),
    path("<int:order_id>/", views.order_detail, name="detail"),
    path("<int:order_id>/review/", views.submit_review_view, name="submit-review"),
    path("<int:order_id>/pack/", views.pack_order_view, name="pack"),
    path("<int:order_id>/dispatch/", views.dispatch_order_view, name="dispatch"),
    path("<int:order_id>/deliver/", views.record_delivery_view, name="deliver"),
    path("<int:order_id>/dispute/", views.open_dispute_view, name="open-dispute"),
    path(
        "dispute/<int:dispute_id>/evidence/",
        views.submit_dispute_evidence_view,
        name="submit-evidence",
    ),
    path("<int:order_id>/fund/", views.fund_order_view, name="fund"),
    path(
        "<int:order_id>/monero-escrow/",
        views.start_monero_escrow_view,
        name="start-monero-escrow",
    ),
    path("<int:order_id>/cancel/", views.cancel_order_view, name="cancel"),
    path("<int:order_id>/accept/", views.accept_order_view, name="accept"),
    path("<int:order_id>/reject/", views.reject_order_view, name="reject"),
    path(
        "<int:order_id>/extend-finalize/",
        views.extend_finalize_view,
        name="extend-finalize",
    ),
]
