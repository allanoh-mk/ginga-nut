from django.urls import path

from core.views import styleguide
from ops import views

app_name = "ops"

urlpatterns = [
    path("styleguide/", styleguide, name="styleguide"),
    path("ops/", views.admin_dashboard, name="dashboard"),
    path("ops/orders/", views.order_list, name="order-list"),
    path(
        "ops/orders/<int:order_id>/force-transition/",
        views.order_force_transition,
        name="order-force-transition",
    ),
    path(
        "ops/market-switch/<str:feature>/toggle/",
        views.market_switch_toggle,
        name="market-switch-toggle",
    ),
    path(
        "ops/withdrawals/",
        views.withdrawal_approval_queue,
        name="withdrawal-approval-queue",
    ),
    path(
        "ops/withdrawals/<int:withdrawal_id>/approve/",
        views.withdrawal_approve,
        name="withdrawal-approve",
    ),
    path(
        "ops/withdrawals/<int:withdrawal_id>/reject/",
        views.withdrawal_reject,
        name="withdrawal-reject",
    ),
    path("reserves/", views.reserve_history, name="reserves"),
    path("canary/", views.public_canary, name="canary"),
    path("health/", views.health, name="health"),
    path("ops/health/", views.health_page, name="health-page"),
]
