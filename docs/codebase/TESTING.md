# Testing and Verification

## Test Stack and Commands

- Primary framework: pytest 8.4.2 with pytest-django 4.9.0 (`requirements.txt`, `pytest.ini`).
- Assertions use pytest assertions and Django test client/TestCase utilities; provider/network boundaries are commonly mocked.
- Commands:

```sh
.venv/bin/pytest -q
.venv/bin/pytest -q orders/tests.py
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python -m coverage run -m pytest
```

Coverage reporting is available as a dependency, but no required coverage threshold was found.

## Test Layout

- App tests are colocated: `accounts/tests.py`, `catalog/tests.py`, `orders/tests.py`, `ledger/tests.py`, `payments/tests.py`, `ops/tests.py`, plus focused `test_*.py` modules.
- Project tests live under `tests/` and include integration journeys, page-size checks, login rate limiting, and settings behavior.
- `pytest.ini` sets `DJANGO_SETTINGS_MODULE=mk.settings` and discovery patterns `tests.py`, `test_*.py`, and `*_tests.py`.
- CI uses Python 3.12 with PostgreSQL 16 and Redis 7 services, then executes `manage.py check`, migration drift checks, and `pytest -q` (`.github/workflows/ci.yml`).

## Test Scope Matrix

| Scope | Covered? | Typical target | Notes |
|---|---|---|---|
| Unit/service | Yes | Ledger posting, state transitions, authentication, commission and provider parsing | Includes validation and some failure paths. |
| Integration | Yes, configured | Django views/forms with ORM; PostgreSQL/Redis and mocked provider edges | Requires configured database/services. |
| End-to-end/browser | Partial/not established | `tests/test_integration.py` exercises HTTP workflows using Django test client | No browser automation or external live-service E2E config found. |
| Live provider | No verified run | BTCPay, TronGrid, Monero, rate feeds, Tor | Use mocks or isolated staging providers; production was not touched. |

## Mocking and Isolation Strategy

- Tests use Django test utilities and mocks/patches for HTTP/provider boundaries; CI provisions ephemeral PostgreSQL/Redis services.
- The checked-in CI sets `DJANGO_DEBUG=true`, enables fake providers, and generates an ephemeral Django secret.
- Database-backed tests are isolated through Django's test database setup. Local run fails before these tests can execute when PostgreSQL is unavailable.

## Coverage and Quality Signals

- Coverage tool: `coverage` 7.17.2. Threshold/current report: [TODO] no valid current report or configured threshold; local coverage report could not find source path `core/services/create_maker_profile.py`.
- Current run: `.venv/bin/python manage.py check` passed with no issues. `.venv/bin/python manage.py makemigrations --check --dry-run` reported no changes, with a warning that PostgreSQL at `127.0.0.1:55439` refused migration-history connection.
- `.venv/bin/pytest --collect-only -q` was attempted: 190 tests collected, collection stopped with one `NameError` in `core/services/watch_chain.py` because return annotation `Deposit` is undefined; 2 more tests appeared after the collection summary due to interrupted output/count reporting. [TODO] Re-run after addressing the collection defect.
- Full tests were not run successfully; PostgreSQL at `127.0.0.1:55439` is unavailable in this workspace.
- Ruff check is available locally but unconfigured in the repo; `.venv/bin/ruff check .` returned findings (first shown in `accounts/admin.py`, `accounts/forms.py`; full output not captured). Do not treat lint as green.
- No verified current browser E2E, load/performance, accessibility, live-provider, or deployment test run.

## Evidence

- `pytest.ini`, `requirements.txt`
- `.github/workflows/ci.yml`
- `accounts/tests.py`, `orders/tests.py`, `payments/tests.py`, `tests/test_integration.py`
- `core/services/watch_chain.py`
- `.venv/bin/python manage.py check` and migration/test command output captured during this review
