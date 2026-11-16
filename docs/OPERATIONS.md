# Operations runbook

## Deployment

All application service units assume a Linux host with the application at
`/opt/kola`, a `kola` service user/group, a Python virtual environment at
`/opt/kola/.venv`, and the application environment at `/opt/kola/.env`.
`monerod.service` uses the same service user and a separate, least-privilege
`/etc/kola/monero.env`. Provision PostgreSQL, Redis, Tor, and provider services
before enabling the application. Do not commit environment files, private
keys, wallet seeds, database passwords, API keys, or rclone credentials.

Create `/opt/kola/.env` as a protected file readable by the `kola` service.
At minimum configure a unique `DJANGO_SECRET_KEY` (50+ characters),
`DJANGO_DEBUG=false`, exact v3 onion hostnames in `DJANGO_ONION_HOSTS`,
PostgreSQL connection values (`POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`), and the queue
`QUEUE_REDIS_URL`. Production settings reject fake chain providers and require
local Monero daemon and Tor proxy endpoints. Complete provider settings below
before starting the web, watcher, and worker services.

From the deployed application directory, install the pinned dependencies and
apply schema changes under the release procedure:

```sh
sudo -u kola /opt/kola/.venv/bin/python -m pip install -r requirements.txt
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py check
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py migrate --noinput
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py collectstatic --noinput
```

Review migration output and take a verified backup before applying schema
changes. Install unit files from `deploy/systemd/`, review their dependencies for the
host, then reload systemd. The web service binds
`127.0.0.1:8000`; configure the existing front proxy to serve the app and route
`/health/` to this endpoint. Start the related units after confirming their
environment files are ready:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mk-web.service mk-worker.service mk-watcher.service
sudo systemctl enable --now kola-scheduler.timer
sudo systemctl status mk-web.service mk-worker.service mk-watcher.service
```

The scheduler and other scheduled reserve/fee units are separate from the web
service. Review and enable the appropriate existing timers from
`deploy/systemd/` for the deployment. If PostgreSQL or Redis is externally
managed, review/remove local service dependencies in the copied units rather
than installing local database services just to satisfy systemd.

## Backups

Configure the encrypted backup system using [BACKUP.md](BACKUP.md) before
enabling `kola-backup.timer`. Backups require a user-selected rclone remote and
encryption key. Check `kola-backup.service` logs after scheduled runs and
periodically perform a controlled restore test to a non-production database.
Do not assume a successful upload is a restorable backup.

## Monitoring and health

`/health/` checks PostgreSQL and Redis; it returns HTTP 503 if either
dependency is unavailable. Configure `/etc/kola/monitor.env` with the
URL reachable from the host, including the correct host required by the
application:

```ini
MONITOR_HEALTH_URL=http://your-configured-host/health/
MONITOR_TIMEOUT_SECONDS=5
```

Do not use the example value literally. Protect the file and ensure the
configured URL is routable and accepted by the Django host configuration. The
monitor runs continuously and polls every 30 seconds. A 503 is logged through
`logger` at `user.err`; other unsuccessful HTTP/network results are logged as
warnings. Review monitor and application logs with:

```sh
sudo systemctl enable --now kola-monitor.service
sudo journalctl -u kola-monitor.service
sudo journalctl -u mk-web.service -u mk-worker.service -u mk-watcher.service
```

This is a health probe, not an alert delivery system; configure the host's
journal/monitoring pipeline to retain and alert on `user.err`.

## Kill switches

The feature switches are database-persisted and exposed in the staff
operations dashboard. To pause new orders:

```sh
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py kill_new_orders
```

To pause withdrawal requests and worker sends:

```sh
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py kill_withdrawals
```

Restore each feature only after the incident is resolved and an operator has
reviewed its state:

```sh
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py kill_new_orders --enable
sudo -u kola /opt/kola/.venv/bin/python /opt/kola/manage.py kill_withdrawals --enable
```

Pausing withdrawals does not discard already queued jobs; they remain queued
until the switch is restored. A reserve-integrity shortfall also disables
withdrawals; restoring them is an explicit operator action, not an automatic
effect of the next successful monitor run.

## Provider configuration

Select actual production provider adapters in `/opt/kola/.env`; fake providers are
development-only and are rejected when `DJANGO_DEBUG=false`. Configure
`BTC_PROVIDER`, `LTC_PROVIDER`, `TRC20_PROVIDER`, and `XMR_PROVIDER` to the
implemented production adapter names in `payments/providers/`. The provider
settings currently read by `mk/settings.py` include:

- BTCPay: `BTCPAY_SERVER_URL`, `BTCPAY_STORE_ID`, `BTCPAY_API_KEY`.
- TronGrid/TRC-20: `TRONGRID_API_URL`, `TRONGRID_API_KEY`,
  `TRC20_CONTRACT_WHITELIST`, `TRC20_RATE_SYMBOL`,
  `TRC20_TOKEN_DECIMALS`, and `TRON_ADDRESS_DERIVER`.
- Monero: `MONERO_WALLET_RPC_URL`, `MONERO_WALLET_RPC_USER`,
  `MONERO_WALLET_RPC_PASSWORD`, plus the role-specific
  `MONERO_RESERVE_WALLET_RPC_*`, `MONERO_HOT_WALLET_RPC_*`, and
  `MONERO_PAYOUT_WALLET_RPC_*` settings. Keep reserve, hot, and payout wallet
  roles separate; the reserve endpoint must be view-only and the payout
  endpoint is the only one that broadcasts withdrawals.
- Local Monero daemon and Tor: `MONEROD_RPC_URL` must be local in production;
  `MONEROD_TOR_PROXY` must point to a local SOCKS listener. The deployed
  `monerod.service` reads `/etc/kola/monero.env`.
- `FIELD_ENCRYPTION_KEY` for encrypted application fields and optional
  `CANARY_STATEMENT` / `CANARY_SIGNING_KEY` for the public signed canary.

Consult the provider module and the project's specification for the exact
requirements of each adapter. Store all credentials in protected environment
files or a secrets manager, use least-privilege provider credentials, and
never put private wallet keys or seed phrases in Kola Market configuration.
Exercise provider changes in a non-production environment before enabling
deposits or withdrawals.
