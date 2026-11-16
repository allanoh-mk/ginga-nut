# External Integrations

## Integration Inventory

| System | Type | Purpose | Auth model | Criticality | Evidence |
|---|---|---|---|---|---|
| PostgreSQL | Database | Primary persistence for users, commerce, payment, ledger, jobs and operations | `POSTGRES_*` credentials | Critical | `mk/settings.py`, `core/models.py` |
| Redis | Queue/cache service | Atomic login throttling and sorted-set financial job queue | Redis URL; deployment network/access controls | High | `mk/settings.py`, `core/services/outbox.py` |
| GnuPG | Local process | OpenPGP challenge verification | Isolated local temporary keyring; signed challenge | High for authentication | `core/services/pgp_auth.py` |
| Coinbase | HTTPS API | Public spot-rate source | Public/keyless via Tor SOCKS5h | High for quote-dependent flows | `payments/providers/rates.py` |
| Kraken | HTTPS API | Second spot-rate source; paired median/divergence checks | Public/keyless via Tor SOCKS5h | High for quote-dependent flows | `payments/providers/rates.py` |
| BTCPay Server | HTTPS API | BTC/LTC invoice/payment polling and wallet balances | Store API token | High for configured chain deposits | `payments/providers/btcpay.py`, `.env.example` |
| TronGrid | HTTPS API | TRC-20 transfer polling, token balances, blacklist checks | Optional API key, allowlisted contracts and local address deriver | High for TRC-20 | `payments/providers/trongrid.py`, `mk/settings.py` |
| Monero wallet RPC + `monerod` | Local HTTP RPC | XMR address/deposit/balance/sweep/withdrawal and reserve operations | Separate role-specific RPC credentials; local endpoints in production | High | `payments/providers/monero.py`, `mk/settings.py` |
| Tor SOCKS listener | Local proxy | Rate-feed egress and documented Monero node peer routing | Local SOCKS endpoint | High for intended network boundary | `payments/providers/rates.py`, `deploy/systemd/monerod.service` |
| Independent Monero escrow gateway | HTTPS API/callback | Optional XMR multisig setup, participant-authorized settlement coordination and balance reporting | Allowlisted host, shared HMAC service credential, timestamp/nonce/sequence checks | Critical if XMR multisig enabled | `payments/monero_escrow_gateway.py`, `docs/MONERO_MULTISIG_ESCROW.md` |
| systemd | Process manager/scheduler | Web, worker, watcher, scheduled ops and backup/restore | Host service account/config files | High | `deploy/systemd/`, `docs/OPERATIONS.md` |
| rclone + age or GPG | Backup transport/crypto tools | Encrypted PostgreSQL backup upload and verification | Deployment-managed remote config and encryption recipient/key | High for recovery | `scripts/backup.sh`, `docs/BACKUP.md` |
| GitHub Actions | CI | Django checks, migration drift check, tests with Postgres/Redis | GitHub workflow runner | Medium/high | `.github/workflows/ci.yml` |

## Data Stores

| Store | Role | Access layer | Key risk | Evidence |
|---|---|---|---|---|
| PostgreSQL | System of record; ledger and outbox persistence | Django ORM; some parameterized SQL in operational commands | Availability and migration-history validation | `mk/settings.py`, `core/services/outbox.py` |
| Redis | Login attempt counters and job delivery queue | `redis` Python client | Queue/limiter outages; durable jobs still need worker/Redis recovery | `core/services/outbox.py`, `core/services/authenticate_user.py` |
| Filesystem | Private uploads and backup staging | Django storage and shell scripts | Deployment must prevent public access to private evidence; backup staging must be protected | `orders/uploads.py`, `docs/BACKUP.md` |

## Secrets and Credentials Handling

- Credentials are read from environment configuration; `.env.example` contains names/placeholders, not a production secret source. Deployment docs require protected files or a secret manager.
- The repository is not a Git checkout in this workspace, so tracked-secret/history status could not be checked; `.env` is excluded by `.gitignore` and was not read.
- Key lifecycle is operationally important: rotating/loss of `FIELD_ENCRYPTION_KEY` without re-encryption makes stored shipping contact unreadable; rate/provider and RPC credentials need deployment management (`docs/SPEC.md`, `docs/OPERATIONS.md`).

## Reliability and Failure Behavior

- Provider HTTP calls use configured timeouts (`RATE_FEED_TIMEOUT_SECONDS`). TronGrid retries request failures with waits of 1, 5, and 25 seconds, and commits its watermark only after polling records are processed (`payments/providers/trongrid.py`, `core/services/poll_deposits.py`).
- Rate collection calls Coinbase and Kraken sequentially; stale or >1%-divergent data should stop quote-dependent operations (`payments/providers/rates.py`, `mk/settings.py`).
- Provider capability defaults fail unsupported balance/send calls explicitly (`payments/providers/base.py`). Fake providers are guarded against production use in settings.
- Financial job records are durable in PostgreSQL; worker errors are stored and retried after 60 seconds. [TODO] Circuit breaker and automated external alerting are not configured (`payments/management/commands/run_market_worker.py`).

## Observability for Integrations

- Python loggers/systemd journal are used; health endpoint checks PostgreSQL and Redis. Reserve integrity logs critical shortfall and warning for unmeasurable chains (`ops/views.py`, `core/services/reserve_integrity.py`).
- No APM, distributed tracing, metrics backend, or external alert-delivery integration was found. The monitor logs probe failures but is not itself alert delivery (`docs/OPERATIONS.md`).
- Live providers, Tor, RPCs, backup destination, and remote signer gateway have not been exercised in this workspace.

## Evidence

- `mk/settings.py`, `.env.example`
- `payments/providers/`, `payments/monero_escrow_gateway.py`
- `core/services/outbox.py`, `payments/management/commands/run_market_worker.py`
- `deploy/systemd/`, `scripts/backup.sh`
- `docs/OPERATIONS.md`, `docs/BACKUP.md`, `docs/MONERO_MULTISIG_ESCROW.md`
