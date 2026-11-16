from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("recovery-login/", views.recovery_login_view, name="recovery_login"),
    path("logout/confirm/", views.logout_confirm_view, name="logout_confirm"),
    path("pgp-auth/", views.pgp_auth_view, name="pgp_auth"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/balance/", views.balance_overview_view, name="balance"),
    path("profile/deposits/", views.deposit_addresses_view, name="deposits"),
    path(
        "profile/deposits/new/",
        views.deposit_address_create,
        name="deposit_address_create",
    ),
    path(
        "profile/deposits/history/",
        views.deposit_history,
        name="deposit_history",
    ),
    path(
        "profile/deposits/<int:deposit_id>/quote/",
        views.deposit_quote_convert_view,
        name="deposit_quote_convert",
    ),
    path(
        "profile/withdrawals/",
        views.withdrawal_history_view,
        name="withdrawals",
    ),
    path(
        "profile/withdrawals/<int:withdrawal_id>/",
        views.withdrawal_detail_view,
        name="withdrawal_detail",
    ),
    path("profile/wallets/", views.wallets_view, name="wallets"),
    path(
        "profile/wallets/challenge/",
        views.wallet_challenge_start_view,
        name="wallet_challenge_start",
    ),
    path(
        "profile/wallets/challenge/<int:challenge_id>/",
        views.wallet_challenge_view,
        name="wallet_challenge",
    ),
    path(
        "profile/wallets/<int:wallet_id>/unlink/",
        views.unlink_wallet_view,
        name="unlink_wallet",
    ),
    path(
        "profile/payout-addresses/",
        views.payout_addresses_view,
        name="payout_addresses",
    ),
    path(
        "profile/payout-addresses/save/",
        views.payout_address_save_view,
        name="payout_address_save",
    ),
    path(
        "profile/payout-addresses/<int:payout_address_id>/delete/",
        views.payout_address_delete_view,
        name="payout_address_delete",
    ),
    path(
        "profile/payout-addresses/<int:payout_address_id>/verify/",
        views.payout_address_verify_start_view,
        name="payout_address_verify_start",
    ),
    path(
        "profile/payout-addresses/verify/<int:challenge_id>/",
        views.payout_address_verify_view,
        name="payout_address_verify",
    ),
    path(
        "profile/recovery-codes/",
        views.regenerate_recovery_codes_view,
        name="regenerate_recovery_codes",
    ),
]
