# Technology Stack

## Runtime Summary

| Area | Value | Evidence |
|---|---|---|
| Primary language | Python | `requirements.txt`, `manage.py` |
| Runtime + version | Python 3.12; Django 5.1.15 | `README.md`, `requirements.txt`, `.github/workflows/ci.yml` |
| Package manager | pip with pinned `requirements.txt`; venv shown in setup docs | `requirements.txt`, `README.md` |
| Module/build system | Django project/apps; no frontend build pipeline | `mk/settings.py`, `mk/urls.py`, `static/css/site.css` |
| Server | Gunicorn WSGI (`mk.wsgi:application`) | `mk/wsgi.py`, `deploy/systemd/mk-web.service` |

## Production Frameworks and Dependencies

| Dependency | Version | Role | Evidence |
|---|---:|---|---|
| Django | 5.1.15 | HTTP, templates, ORM, sessions, admin, migrations | `requirements.txt`, `mk/settings.py` |
| psycopg[binary] | 3.2.13 | PostgreSQL driver | `requirements.txt`, `mk/settings.py` |
| redis | 5.3.1 | Login throttling and financial-job queue | `requirements.txt`, `core/services/outbox.py` |
| gunicorn | 23.0.0 | WSGI server | `requirements.txt`, `deploy/systemd/mk-web.service` |
| argon2-cffi | 23.1.0 | Password hashing | `requirements.txt`, `mk/settings.py` |
| cryptography | 50.0.2 | Fernet encrypted order contact data | `requirements.txt`, `orders/fields.py` |
| tronpy | 0.7.0 | TRON address/signature validation and provider support | `requirements.txt`, `core/services/_wallet_linking.py`, `payments/providers/trongrid.py` |
| requests | 2.32.5 | Provider and rate-feed HTTP clients | `requirements.txt`, `payments/providers/` |
| PySocks | 1.7.1 | SOCKS proxy support for Tor rate-feed egress | `requirements.txt`, `payments/providers/rates.py` |
| Pillow | 11.3.0 | Image validation/processing | `requirements.txt`, `orders/uploads.py` |
| python-dotenv | 1.2.4 | Loads local `.env` settings | `requirements.txt`, `mk/settings.py` |

## Development Toolchain

| Tool | Purpose | Evidence |
|---|---|---|
| pytest + pytest-django | Test runner and Django integration | `requirements.txt`, `pytest.ini`, `.github/workflows/ci.yml` |
| coverage | Coverage reporting package; no enforced threshold found | `requirements.txt`, `.coverage` ignored by `.gitignore` |
| Ruff | Present in local `.venv`; no checked-in Ruff configuration found | `docs/codebase/.codebase-scan.txt`; `[TODO]` whether team-standard/lint config is maintained elsewhere |
| GnuPG (`gpg`) | Runtime dependency for OpenPGP authentication | `README.md`, `core/services/pgp_auth.py` |

## Key Commands

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py runserver
pytest -q
python manage.py makemigrations --check --dry-run
```

## Environment and Config

- Config sources: `mk/settings.py`, `.env.example`, `README.md`, `docs/OPERATIONS.md`.
- Core environment: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, host/CSRF settings, `POSTGRES_*`, `QUEUE_REDIS_URL`, `LOGIN_RATE_LIMIT_REDIS_URL`.
- Payment/provider settings include `BTC_PROVIDER`, `LTC_PROVIDER`, `TRC20_PROVIDER`, `XMR_PROVIDER`, BTCPay/TronGrid/Monero settings, rate-feed Tor proxy, and `FIELD_ENCRYPTION_KEY`; see `.env.example` for the complete list.
- Runtime constraints: PostgreSQL and Redis; production uses onion host validation and disallows fake chain providers. GnuPG and provider/RPC/Tor setup are needed for corresponding flows. Production deployment is documented for systemd/Gunicorn on Linux.

## Evidence

- `requirements.txt`
- `mk/settings.py`, `mk/wsgi.py`
- `.env.example`, `README.md`
- `.github/workflows/ci.yml`
- `core/services/pgp_auth.py`, `orders/fields.py`, `payments/providers/`
