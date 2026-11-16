# Kola Market

Kola Market is a server-rendered Django marketplace with vendor listings, physical-order checkout, an append-only ledger, deposits and withdrawals, order escrow/disputes, reviews, and in-app notifications. See [`docs/SPEC.md`](docs/SPEC.md) for product and money-flow rules and [`docs/MARKETPLACE_AUDIT.md`](docs/MARKETPLACE_AUDIT.md) for implementation status and known limitations.

## Requirements

- Python 3.12
- PostgreSQL
- Redis
- GnuPG (`gpg`) for account enrollment/login challenges
- Tor SOCKS5 listener for live exchange-rate feeds (optional for tests/local flows)

## Local setup

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Set `DJANGO_SECRET_KEY` to a generated secret and configure the local PostgreSQL and Redis connection values in `.env`. Keep all credentials local; do not commit `.env`. For a normal local development environment, retain `DJANGO_DEBUG=true` and fake chain providers until the corresponding provider integrations are intentionally configured.

Create the PostgreSQL database and user named in `.env`, start Redis, then run:

```sh
python manage.py migrate
python manage.py check
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Account creation and login require the OpenPGP challenge flow; local development therefore also requires a working `gpg` executable. Real deposits, withdrawals, Tor rate feeds, and Monero multisig escrow require additional provider/RPC configuration described in [`.env.example`](.env.example) and [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Tests and checks

Start PostgreSQL and Redis using the same connection settings as `.env`, then run:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
```

Database-backed tests require PostgreSQL and Redis. The CI workflow provisions both services. Provider integration tests should use mocks or explicitly provisioned test services; never point tests at production wallets or provider credentials.

## Operations

Systemd units and timers are in [`deploy/systemd/`](deploy/systemd/). Follow [docs/OPERATIONS.md](docs/OPERATIONS.md) for deployment, monitoring, providers, and kill switches, and [docs/BACKUP.md](docs/BACKUP.md) for backup and restore configuration.

## Architecture

The request path is URL configuration → server-rendered view/form → `core/services/` domain operation → Django ORM/PostgreSQL. Redis is used for login throttling and worker queues; financial jobs are persisted in an outbox and published after transaction commit. Provider adapters isolate chain and rate-feed APIs. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
# ginga-nut
