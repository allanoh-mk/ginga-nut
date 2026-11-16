import os
import subprocess
import sys

from django.apps import apps
from django.conf import settings
from django.test import override_settings
from django.urls import path, reverse

from mk.urls import urlpatterns as project_urlpatterns


def raise_test_error(request):
    raise RuntimeError("test-only failure")


urlpatterns = [*project_urlpatterns, path("test-error/", raise_test_error)]
handler500 = "mk.urls.server_error"


def test_marketplace_apps_are_registered() -> None:
    app_names = {"accounts", "catalog", "orders", "ledger", "ops"}

    assert all(apps.is_installed(name) for name in app_names)


def test_root_redirects_to_catalog(client) -> None:
    response = client.get("/")

    assert response.status_code == 301
    assert response["Location"] == "/catalog/"


def test_unknown_route_renders_branded_404(client) -> None:
    with override_settings(DEBUG=False):
        response = client.get("/route-that-does-not-exist/")

    assert response.status_code == 404
    assert b"Page not found" in response.content
    assert b"Browse" in response.content


def test_server_error_renders_branded_500_without_traceback(client) -> None:
    client.raise_request_exception = False
    with override_settings(DEBUG=False, ROOT_URLCONF=__name__):
        response = client.get("/test-error/")

    assert response.status_code == 500
    assert b"Something went wrong" in response.content
    assert b"Traceback" not in response.content
    assert b"Browse" in response.content


def test_database_uses_postgresql() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_queue_has_a_redis_url() -> None:
    assert settings.QUEUE_REDIS_URL.startswith(("redis://", "rediss://"))


def test_session_settings_match_the_specification() -> None:
    assert settings.SESSION_COOKIE_AGE == 30 * 60
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SECURE is False
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"


def test_secret_key_is_not_a_development_fallback() -> None:
    assert settings.SECRET_KEY != "local-development-key-replace-before-deployment"
    assert len(settings.SECRET_KEY) >= 50
    assert len(set(settings.SECRET_KEY)) >= 20


def test_production_host_guard_rejects_non_onion_hosts(client) -> None:
    onion_host = f"{'a' * 56}.onion"
    with override_settings(
        ONION_ONLY=True,
        ONION_HOSTS=[onion_host],
        ALLOWED_HOSTS=[onion_host],
    ):
        rejected = client.get(
            reverse("accounts:login"),
            HTTP_HOST="clearnet.example",
        )
        accepted = client.get(
            reverse("accounts:login"),
            HTTP_HOST=onion_host,
        )

    assert rejected.status_code == 400
    assert accepted.status_code == 200


def test_production_settings_fail_without_a_valid_onion_host() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "mk.settings",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": (
                "test-secret-key-0123456789-abcdefghijk-lmnopqrstuvwxyz-ABCDE"
            ),
            "DJANGO_ONION_HOSTS": "",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.ONION_ONLY)",
        ],
        capture_output=True,
        cwd=settings.BASE_DIR,
        env=environment,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "Production requires DJANGO_ONION_HOSTS" in result.stderr


def test_production_settings_reject_a_public_monerod_rpc_url() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "mk.settings",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": (
                "test-secret-key-0123456789-abcdefghijk-lmnopqrstuvwxyz-ABCDE"
            ),
            "DJANGO_ONION_HOSTS": f"{'d' * 56}.onion",
            "MONEROD_RPC_URL": "https://public-node.example/json_rpc",
            "BTC_PROVIDER": "btcpay",
            "LTC_PROVIDER": "btcpay",
            "TRC20_PROVIDER": "trongrid",
            "XMR_PROVIDER": "monero_wallet_rpc",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.MONEROD_RPC_URL)",
        ],
        capture_output=True,
        cwd=settings.BASE_DIR,
        env=environment,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "MONEROD_RPC_URL must point to a localhost RPC endpoint" in result.stderr


def test_production_settings_reject_fake_chain_providers() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "mk.settings",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": (
                "test-secret-key-0123456789-abcdefghijk-lmnopqrstuvwxyz-ABCDE"
            ),
            "DJANGO_ONION_HOSTS": f"{'e' * 56}.onion",
            "BTC_PROVIDER": "fake",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.CHAIN_PROVIDERS)",
        ],
        capture_output=True,
        cwd=settings.BASE_DIR,
        env=environment,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "Fake chain providers are forbidden" in result.stderr


def test_fake_providers_can_be_enabled_only_with_debug() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "mk.settings",
            "DJANGO_DEBUG": "true",
            "ALLOW_FAKE_PROVIDERS": "true",
            "DJANGO_SECRET_KEY": (
                "test-secret-key-0123456789-abcdefghijk-lmnopqrstuvwxyz-ABCDE"
            ),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.ALLOW_FAKE_PROVIDERS)",
        ],
        capture_output=True,
        cwd=settings.BASE_DIR,
        env=environment,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "True"


def test_allow_fake_providers_does_not_bypass_production_guard() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "mk.settings",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": (
                "test-secret-key-0123456789-abcdefghijk-lmnopqrstuvwxyz-ABCDE"
            ),
            "DJANGO_ONION_HOSTS": f"{'f' * 56}.onion",
            "ALLOW_FAKE_PROVIDERS": "true",
            "BTC_PROVIDER": "btcpay",
            "LTC_PROVIDER": "btcpay",
            "TRC20_PROVIDER": "trongrid",
            "XMR_PROVIDER": "monero_wallet_rpc",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.ALLOW_FAKE_PROVIDERS)",
        ],
        capture_output=True,
        cwd=settings.BASE_DIR,
        env=environment,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "ALLOW_FAKE_PROVIDERS requires DJANGO_DEBUG=True" in result.stderr


def test_settings_reject_a_low_entropy_secret() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "mk.settings",
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "x" * 60,
            "DJANGO_ONION_HOSTS": f"{'c' * 56}.onion",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; print(settings.SECRET_KEY)",
        ],
        capture_output=True,
        cwd=settings.BASE_DIR,
        env=environment,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY must be set" in result.stderr
