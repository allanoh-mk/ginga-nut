# Architecture Overview

## Architectural Style

- Primary style: server-rendered Django application organized by domain apps, with a shared service layer and asynchronous/outbox-backed operational work.
- Evidence: app-owned persistence/HTTP surfaces coexist with cross-app domain operations under `core/services/`; provider adapters isolate external calls; financial jobs use PostgreSQL records published to Redis.
- Primary constraints: server-side HTML/no frontend state; PostgreSQL is financial/application source of truth; ledger/state mutations flow through transactional services and provider boundaries.

## System Flow

```text
Browser -> mk.urls -> app view/form -> core.services -> Django ORM/PostgreSQL
                                            |                  |
                                            +-> FinancialJob --+-> on_commit -> Redis -> worker -> service/provider
systemd timer -> manage.py command -> service/provider -> PostgreSQL and external RPC/API
```

1. `mk/urls.py` composes project and app URL configurations.
2. Views handle HTTP methods, authentication/authorization, and form validation; templates render server-side pages.
3. Domain services in `core/services/` implement state changes and transaction logic.
4. Django models/migrations persist the state in PostgreSQL; ledger balances are aggregates over immutable entries.
5. A durable financial job is written within a transaction and placed on the Redis sorted-set queue after commit; workers claim/retry jobs.
6. Scheduled management commands call the same services and provider adapters; adapters communicate with chain APIs/RPCs and rate sources.

## Layer/Module Responsibilities

| Module | Owns | Must not own | Evidence |
|---|---|---|---|
| `mk/` | Settings, root URLs, Django entry points, project-level rendering/config | Domain operation logic | `mk/settings.py`, `mk/urls.py`, `mk/wsgi.py` |
| Domain apps | App models, views, forms, routes, templates, migrations and admin | Shared cross-domain financial rules | `accounts/`, `catalog/`, `orders/`, `payments/`, `ledger/`, `ops/` |
| `core/services/` | Shared business operations, state transitions, ledger postings, queues, reserve operations | HTML template rendering and provider HTTP specifics | `core/services/post_transfer.py`, `core/services/order_transitions.py` |
| `payments/providers/` | Provider-specific address, polling, balance, send, and rates behavior | User authorization/domain policy | `payments/providers/base.py`, `payments/providers/__init__.py` |
| `core/outbox` + worker | Durable job records, after-commit enqueue, claim/retry/dispatch | Treating Redis as sole financial source of truth | `core/services/outbox.py`, `payments/management/commands/run_market_worker.py` |
| `deploy/systemd/` | Host process and schedule definitions | Application-level business logic | `deploy/systemd/`, `docs/OPERATIONS.md` |

## Reused Patterns

| Pattern | Where found | Purpose |
|---|---|---|
| Provider adapter/factory | `payments/providers/base.py`, `payments/providers/__init__.py` | Declare capabilities and select chain-specific implementations. |
| Service modules | `core/services/` | Keep sensitive domain operations testable and callable from HTTP and command contexts. |
| Explicit transition table | `core/services/order_transitions.py` | Reject invalid order state/action pairs. |
| Transactional outbox | `core/services/outbox.py`, `core/models.py` | Persist financial work with the database transaction and publish after commit. |
| Append-only ledger | `ledger/models.py`, `core/services/post_transfer.py` | Represent value movement as paired immutable signed entries. |

## Known Architectural Risks

- Financial/provider correctness and production behavior are not validated against live services; the external Monero signer gateway is not included. See `docs/MONERO_MULTISIG_ESCROW.md` and `docs/codebase/CONCERNS.md`.
- Some integrations run sequentially, including rate source requests and chain polling; TronGrid may rescan old pages because its account-transfer endpoint has no block filter (`payments/providers/rates.py`, `payments/providers/trongrid.py`).
- Balance aggregation work grows with ledger history (`ledger/models.py`, `core/services/post_transfer.py`).
- Redis and the worker are required for queued operations; job records are durable but pending/failed-job alerting is not established (`core/services/outbox.py`, `docs/MARKETPLACE_AUDIT.md`).

## Evidence

- `mk/urls.py`, `mk/settings.py`, `mk/wsgi.py`
- `core/services/post_transfer.py`, `core/services/order_transitions.py`, `core/services/outbox.py`
- `ledger/models.py`, `core/models.py`
- `payments/providers/`, `payments/management/commands/run_market_worker.py`
- `deploy/systemd/`, `docs/ARCHITECTURE.md`
