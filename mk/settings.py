import os
import re
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if (
    len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 20
    or SECRET_KEY == "local-development-key-replace-before-deployment"
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a unique secret of at least 50 characters."
    )


def _csv_setting(name: str, default: str = "") -> list[str]:
    values = os.environ.get(name, default).split(",")
    return [value.strip() for value in values if value.strip()]


ONION_ONLY = not DEBUG
ONION_HOSTS = _csv_setting("DJANGO_ONION_HOSTS")
if ONION_ONLY:
    if not ONION_HOSTS or any(
        re.fullmatch(r"[a-z2-7]{56}\.onion", host) is None for host in ONION_HOSTS
    ):
        raise ImproperlyConfigured(
            "Production requires DJANGO_ONION_HOSTS with exact v3 .onion hostnames."
        )
    ALLOWED_HOSTS = ONION_HOSTS
    CSRF_TRUSTED_ORIGINS = [f"http://{host}" for host in ONION_HOSTS]
else:
    ALLOWED_HOSTS = _csv_setting(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,testserver",
    )
    CSRF_TRUSTED_ORIGINS = _csv_setting("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "mk.admin_config.PGPAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "accounts.apps.AccountsConfig",
    "catalog.apps.CatalogConfig",
    "orders.apps.OrdersConfig",
    "ledger.apps.LedgerConfig",
    "payments.apps.PaymentsConfig",
    "ops.apps.OpsConfig",
]
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.OnionHostMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.PGPAuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mk.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "mk" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.market_identity",
            ],
        },
    },
]

FORM_RENDERER = "mk.form_renderers.KolaFormRenderer"

WSGI_APPLICATION = "mk.wsgi.application"
ASGI_APPLICATION = "mk.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "kola_market"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

QUEUE_REDIS_URL = os.environ.get(
    "QUEUE_REDIS_URL",
    "redis://127.0.0.1:6379/0",
)
MARKET_BASE_UNITS_PER_WHOLE = 100_000_000
MARKET_WITHDRAWAL_MAX_TX_BASE_UNITS = int(
    os.environ.get("WITHDRAWAL_MAX_TX_BASE_UNITS", "200000000")
)
MARKET_WITHDRAWAL_MAX_HOURLY_BASE_UNITS = int(
    os.environ.get("WITHDRAWAL_MAX_HOURLY_BASE_UNITS", "1500000000")
)
MARKET_WITHDRAWAL_MAX_DAILY_BASE_UNITS = int(
    os.environ.get("WITHDRAWAL_MAX_DAILY_BASE_UNITS", "6000000000")
)
MARKET_CHAIN_CONFIRMATIONS = {
    "BTC": int(os.environ.get("BTC_CONFIRMATIONS", "2")),
    "LTC": int(os.environ.get("LTC_CONFIRMATIONS", "6")),
    "TRC20": int(os.environ.get("TRC20_CONFIRMATIONS", "20")),
    "XMR": int(os.environ.get("XMR_CONFIRMATIONS", "10")),
}
RATE_FEED_SOCKS_PROXY = os.environ.get(
    "RATE_FEED_SOCKS_PROXY",
    "socks5h://127.0.0.1:9050",
)
RATE_FEED_STALE_SECONDS = 5 * 60
RATE_QUOTE_LOCK_SECONDS = 10 * 60
RATE_FEED_TIMEOUT_SECONDS = int(os.environ.get("RATE_FEED_TIMEOUT_SECONDS", "10"))
CHAIN_PROVIDERS = {
    "BTC": os.environ.get("BTC_PROVIDER", "fake"),
    "LTC": os.environ.get("LTC_PROVIDER", "fake"),
    "TRC20": os.environ.get("TRC20_PROVIDER", "fake"),
    "XMR": os.environ.get("XMR_PROVIDER", "fake"),
}
ALLOW_FAKE_PROVIDERS = os.environ.get("ALLOW_FAKE_PROVIDERS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
if ALLOW_FAKE_PROVIDERS and not DEBUG:
    raise ImproperlyConfigured(
        "ALLOW_FAKE_PROVIDERS requires DJANGO_DEBUG=True and must not be used in production."
    )
if not DEBUG and any(provider == "fake" for provider in CHAIN_PROVIDERS.values()):
    raise ImproperlyConfigured(
        "Fake chain providers are forbidden when DJANGO_DEBUG=False."
    )
TRC20_CONTRACT_WHITELIST = _csv_setting("TRC20_CONTRACT_WHITELIST")
TRC20_RATE_SYMBOL = os.environ.get("TRC20_RATE_SYMBOL", "")
TRC20_TOKEN_DECIMALS = int(os.environ.get("TRC20_TOKEN_DECIMALS", "6"))
BTCPAY_SERVER_URL = os.environ.get("BTCPAY_SERVER_URL", "")
BTCPAY_STORE_ID = os.environ.get("BTCPAY_STORE_ID", "")
BTCPAY_API_KEY = os.environ.get("BTCPAY_API_KEY", "")
TRONGRID_API_URL = os.environ.get("TRONGRID_API_URL", "")
TRONGRID_API_KEY = os.environ.get("TRONGRID_API_KEY", "")
TETHER_TRC20_CONTRACT = os.environ.get(
    "TETHER_TRC20_CONTRACT",
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
)
TRON_ADDRESS_DERIVER = os.environ.get("TRON_ADDRESS_DERIVER", "")
MONERO_WALLET_RPC_URL = os.environ.get("MONERO_WALLET_RPC_URL", "")
MONERO_WALLET_RPC_USER = os.environ.get("MONERO_WALLET_RPC_USER", "")
MONERO_WALLET_RPC_PASSWORD = os.environ.get("MONERO_WALLET_RPC_PASSWORD", "")
MONERO_RESERVE_WALLET_RPC_URL = os.environ.get(
    "MONERO_RESERVE_WALLET_RPC_URL",
    MONERO_WALLET_RPC_URL,
)
MONERO_HOT_WALLET_RPC_URL = os.environ.get("MONERO_HOT_WALLET_RPC_URL", "")
MONERO_PAYOUT_WALLET_RPC_URL = os.environ.get("MONERO_PAYOUT_WALLET_RPC_URL", "")
MONERO_RESERVE_WALLET_RPC_USER = os.environ.get(
    "MONERO_RESERVE_WALLET_RPC_USER",
    MONERO_WALLET_RPC_USER,
)
MONERO_RESERVE_WALLET_RPC_PASSWORD = os.environ.get(
    "MONERO_RESERVE_WALLET_RPC_PASSWORD",
    MONERO_WALLET_RPC_PASSWORD,
)
MONERO_HOT_WALLET_RPC_USER = os.environ.get("MONERO_HOT_WALLET_RPC_USER", "")
MONERO_HOT_WALLET_RPC_PASSWORD = os.environ.get("MONERO_HOT_WALLET_RPC_PASSWORD", "")
MONERO_PAYOUT_WALLET_RPC_USER = os.environ.get("MONERO_PAYOUT_WALLET_RPC_USER", "")
MONERO_PAYOUT_WALLET_RPC_PASSWORD = os.environ.get(
    "MONERO_PAYOUT_WALLET_RPC_PASSWORD",
    "",
)
MONERO_ESCROW_GATEWAY_URL = (
    os.environ.get(
        "MONERO_ESCROW_GATEWAY_URL",
        "",
    )
    .strip()
    .rstrip("/")
)
MONERO_ESCROW_GATEWAY_ALLOWED_HOSTS = _csv_setting(
    "MONERO_ESCROW_GATEWAY_ALLOWED_HOSTS"
)
MONERO_ESCROW_GATEWAY_SECRET = os.environ.get(
    "MONERO_ESCROW_GATEWAY_SECRET",
    "",
).strip()
MONERO_ESCROW_CALLBACK_URL = os.environ.get(
    "MONERO_ESCROW_CALLBACK_URL",
    "",
).strip()
MONERO_ESCROW_RELEASE_ADDRESS = os.environ.get(
    "MONERO_ESCROW_RELEASE_ADDRESS",
    "",
).strip()
MONEROD_RPC_URL = os.environ.get("MONEROD_RPC_URL", "")
MONEROD_TOR_PROXY = os.environ.get(
    "MONEROD_TOR_PROXY",
    "127.0.0.1:9050",
)
if ONION_ONLY:
    monerod_url = urlparse(MONEROD_RPC_URL)
    proxy_host, separator, proxy_port = MONEROD_TOR_PROXY.rpartition(":")
    if monerod_url.scheme not in {"http", "https"} or monerod_url.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ImproperlyConfigured(
            "Production MONEROD_RPC_URL must point to a localhost RPC endpoint."
        )
    if (
        not separator
        or proxy_host.strip("[]") not in {"localhost", "127.0.0.1", "::1"}
        or not proxy_port.isdigit()
        or not 1 <= int(proxy_port) <= 65535
    ):
        raise ImproperlyConfigured(
            "Production MONEROD_TOR_PROXY must use a localhost SOCKS port."
        )
RESERVE_HOT_BALANCE_BASE_UNITS = int(
    os.environ.get("RESERVE_HOT_BALANCE_BASE_UNITS", "0")
)
RESERVE_COLD_BALANCE_BASE_UNITS = int(
    os.environ.get("RESERVE_COLD_BALANCE_BASE_UNITS", "0")
)
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY")
CANARY_STATEMENT = os.environ.get("CANARY_STATEMENT", "")
CANARY_SIGNING_KEY = os.environ.get("CANARY_SIGNING_KEY", "")
LOGIN_RATE_LIMIT_REDIS_URL = os.environ.get(
    "LOGIN_RATE_LIMIT_REDIS_URL",
    QUEUE_REDIS_URL,
)
LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 15 * 60

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"

SESSION_COOKIE_AGE = 30 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
