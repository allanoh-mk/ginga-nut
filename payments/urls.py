from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    path(
        "monero-escrow/events/",
        views.monero_escrow_callback,
        name="monero-escrow-callback",
    ),
]
