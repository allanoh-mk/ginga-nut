# Codebase Structure

## Top-Level Map

| Path | Purpose | Evidence |
|---|---|---|
| `mk/` | Django settings, root routes, WSGI/ASGI, admin and form configuration | `mk/settings.py`, `mk/urls.py`, `mk/wsgi.py` |
| `accounts/` | Custom user/authentication and account/payment pages | `accounts/models.py`, `accounts/views.py`, `accounts/urls.py` |
| `catalog/` | Vendor profiles, categories, listings, reviews, discovery | `catalog/models.py`, `catalog/views.py` |
| `orders/` | Orders, fulfillment, disputes, evidence, order pages | `orders/models.py`, `orders/views.py` |
| `ledger/` | Ledger accounts/entries and reconciliation command | `ledger/models.py`, `ledger/management/commands/reconcile.py` |
| `payments/` | Payment models, provider adapters, gateway, worker commands | `payments/models.py`, `payments/providers/`, `payments/management/commands/` |
| `ops/` | Staff dashboards, switches, reserve/health functionality | `ops/models.py`, `ops/views.py` |
| `core/` | Cross-app models, views, middleware, jobs, and domain services | `core/models.py`, `core/services/`, `core/middleware.py` |
| `static/css/` | Hand-written site styling; no frontend build system | `static/css/site.css`, `mk/settings.py` |
| `deploy/systemd/` | Web, worker, watcher, scheduler, backup, monitor, reserve and sweep units | `deploy/systemd/` |
| `scripts/` | Backup/restore and project/page utility scripts | `scripts/` |
| `tests/` | Project-wide settings, integration, page-size, and rate-limit tests | `tests/` |
| `docs/` | Product specification, operations, audit, architecture, and codebase notes | `docs/SPEC.md`, `docs/OPERATIONS.md`, `docs/MARKETPLACE_AUDIT.md` |
| `.github/workflows/` | CI workflow | `.github/workflows/ci.yml` |

## Entry Points

- Main runtime entry: `manage.py`; WSGI application `mk.wsgi:application`, ASGI application `mk.asgi:application`.
- HTTP root and app routing: `mk/urls.py` includes account, catalog, order, payment, notification, and operations routes.
- Secondary entry points: Django management commands under `*/management/commands/`; systemd service/timer units under `deploy/systemd/` run web, worker, watcher, scheduler, reserve, backup, and monitoring processes.
- CI entry: `.github/workflows/ci.yml` provisions PostgreSQL/Redis and runs checks/tests.

## Module Boundaries

| Boundary | What belongs here | Must not be here | Evidence |
|---|---|---|---|
| Django apps | App-owned models, views/forms, routes, templates, migrations, admin, tests | Cross-domain business logic where shared domain service exists | `accounts/`, `catalog/`, `orders/`, `payments/`, `ledger/`, `ops/` |
| `core/services/` | Domain operations spanning requests/jobs/apps; typically one public operation per module | HTTP rendering or provider-specific transport details | `CONVENTIONS.md`, `core/services/` |
| `payments/providers/` | Chain/rate integration adapters and capability declarations | View/business policy | `payments/providers/base.py`, `payments/providers/__init__.py` |
| Templates and CSS | Server-rendered HTML and shared stylesheet | Client-side application state or external CDN assets per project constraints | `mk/settings.py`, `CONVENTIONS.md`, `static/css/site.css` |
| `deploy/` and `scripts/` | Host-level systemd and backup/restore operations | Committed deployment secrets | `docs/OPERATIONS.md`, `.env.example` |

## Naming and Organization Rules

- Python modules and functions use `snake_case`; classes use `PascalCase`; constants use uppercase names. Examples: `core/services/post_transfer.py`, `post_transfer`, `LedgerEntry`, `ORDER_TRANSITIONS`.
- App modules are grouped by domain; cross-app services are mostly one operation per module, named for the operation.
- No project import alias/path-mapping configuration was found; imports use package paths such as `core.services.post_transfer`.
- Migrations are app-local and additive per `CONVENTIONS.md` and `docs/SPEC.md`.

## Evidence

- `mk/urls.py`, `mk/settings.py`, `manage.py`
- `core/services/`, `payments/providers/`
- `deploy/systemd/`, `scripts/`, `.github/workflows/ci.yml`
- `CONVENTIONS.md`, `docs/SPEC.md`
