# Coding Conventions

## Naming Rules

| Item | Rule | Example | Evidence |
|---|---|---|---|
| Files/modules | `snake_case.py`, domain-grouped | `post_transfer.py`, `order_transitions.py` | `core/services/` |
| Functions/variables | `snake_case` | `post_transfer`, `amount_base_units` | `core/services/post_transfer.py` |
| Classes | `PascalCase` | `LedgerEntry`, `ChainProvider` | `ledger/models.py`, `payments/providers/base.py` |
| Constants | Uppercase with underscores | `ORDER_TRANSITIONS`, `FINANCIAL_JOB_QUEUE` | `core/services/order_transitions.py`, `core/jobs.py` |
| Environment variables | Uppercase with underscores | `DJANGO_SECRET_KEY`, `QUEUE_REDIS_URL` | `.env.example`, `mk/settings.py` |

## Formatting and Linting

- Formatter: [TODO] No checked-in formatter configuration was found in the root scan.
- Linter: [TODO] No checked-in linter configuration was found. Ruff exists in the current local `.venv`, but that alone does not establish a repository-mandated lint command.
- Project requirements emphasize exact dependency pins, server-rendered HTML, a single hand-written mobile-first stylesheet, and additive migrations (`CONVENTIONS.md`).
- Run commands: project-documented checks are `python manage.py check`, `python manage.py makemigrations --check --dry-run`, and `pytest -q` (`README.md`).

## Import and Module Conventions

- Imports use explicit package paths; no alias/path mapping or barrel-export convention was found.
- Django apps own app-specific models, views, forms, routes, templates, migrations, and tests; cross-app business operations are organized under `core/services/`.
- Service modules are generally operation-named with a public function (stated in root `CONVENTIONS.md`); there are deliberate private helpers such as `_wallet_linking.py`.
- State-changing requests use POST with CSRF protection; views should delegate domain changes to services (`CONVENTIONS.md`, `docs/codebase/ARCHITECTURE.md`).

## Error and Logging Conventions

- Domain/provider validation raises Django `ValidationError`, typed exceptions, or `ValueError`/`ProviderError`; views and worker boundaries translate/catch expected failures where implemented.
- Logging uses Python's standard `logging` module. Operational reserve concerns include contextual run IDs and chain names (`core/services/reserve_integrity.py`).
- Secrets are environment-configured and should not be committed. PGP verification uses bounded subprocess execution and isolated temporary directories; sensitive order contact fields are encrypted at the model field boundary (`core/services/pgp_auth.py`, `orders/fields.py`, `CONVENTIONS.md`).
- [TODO] A project-wide structured logging format and redaction policy are not defined in the inspected configuration.

## Testing Conventions

- Test files are colocated in apps (`tests.py`, `test_*.py`) with project-wide tests in `tests/`; pytest discovery is configured by `pytest.ini`.
- Tests use pytest/pytest-django, Django test utilities, and mocks for provider/network boundaries; database-backed tests require PostgreSQL and Redis services as configured in CI.
- Root convention requests coverage for each service including failure paths, but no coverage threshold is configured (`CONVENTIONS.md`, `requirements.txt`).

## Evidence

- `CONVENTIONS.md`, `pytest.ini`, `requirements.txt`
- `core/services/post_transfer.py`, `core/services/order_transitions.py`
- `payments/providers/base.py`, `core/services/pgp_auth.py`
- `orders/fields.py`, `.github/workflows/ci.yml`
