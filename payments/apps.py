from django.apps import AppConfig
from django.conf import settings


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def ready(self) -> None:
        if (
            settings.ONION_ONLY
            and settings.CHAIN_PROVIDERS.get("XMR") == "monero_wallet_rpc"
        ):
            from payments.providers.monero import MoneroWalletProvider

            MoneroWalletProvider().validate_at_startup()
