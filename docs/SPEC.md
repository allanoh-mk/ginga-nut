# Kola Market specification

## Product and scope

Kola Market is a multi-vendor marketplace with buyers, vendors, and an admin. Vendors list products in categories. Buyers place orders using an internal balance. Order funds remain in escrow until delivery is confirmed or an admin rules on a dispute.

Vendor profiles require admin approval before vendors can create or manage listings. Listings have a title, description, integer `base` price, stock quantity, category, and active flag. Only active listings from approved vendors are public. The initial vendor profile contains its owner, approval flag, and bond amount; a vendor application starts pending with a zero bond. Bond amount is derived from the profile's dedicated `vendor_bond` ledger account, not stored as a mutable balance. Bond funding and adjustment are not implemented in the catalog.

There is no buyer-level card processor or external payment API. Deposits and withdrawals cross the system boundary through provider modules. No email is used; notifications are in-app.

## Hard technical constraints

- Python 3.12 and Django 5.1, with exact dependency pins in `requirements.txt`.
- PostgreSQL is the application database. Redis is the queue backend.
- HTML is server-rendered. There is no client-side JavaScript; every interaction is a form `POST` followed by a redirect.
- Use one hand-written, mobile-first stylesheet. The total page weight target is under 40 KB. Do not use CDN assets or frontend frameworks.
- Business logic belongs in `core/services/`, with one public function per service module. Views contain no business logic.
- State machines use explicit enums and a transition table. Any transition not in the table raises.
- Every service has pytest coverage, including failure paths.
- Migrations are additive; never edit a shipped migration.

## Ledger and money

The ledger currency is the abstract unit `base`. Amounts are integers at eight decimal places: one whole `base` is represented by 100,000,000 ledger units. No coin name is hardcoded outside a provider module. No floats or rounded `Decimal` operations are used for ledger amounts.
For quotes, one whole `base` is a USD-equivalent reference unit; this is a pricing convention, not a redemption guarantee.

The ledger is double-entry and append-only. There is no mutable balance column; balances are aggregated from ledger rows. The global sum across all accounts must always be zero. `reconcile` asserts that invariant; a reconciliation failure freezes withdrawals until resolved.

Exactly these ledger account purposes are seeded by a data migration:

| Purpose | Meaning |
|---|---|
| `external` | Counter-account for anything crossing the system boundary |
| `user_available` | Buyer spendable balance |
| `user_escrow` | Order funds held pending delivery |
| `vendor_available` | Vendor withdrawable balance |
| `vendor_bond` | Vendor bond, slashed on ruling |
| `market_fee` | Order and 3% deposit/withdrawal commissions |
| `market_spread` | Legacy spread balance retained for treasury sweep |
| `treasury` | Operator equity |
| `suspense` | Unmatched or under-minimum deposits |

Deposits post the net amount `external → user_available` and the commission `external → market_fee`. Withdrawals reserve the gross amount from the user's positive `user_available` and/or `vendor_available` balances, then settle the net amount to `external` and the commission to `market_fee`.

`Account.Kind` defines the account purposes in the table; system accounts are seeded by [`ledger/migrations/0006_seed_account_registry.py`](../ledger/migrations/0006_seed_account_registry.py).

Ledger entries are immutable at the model/queryset layer and protected from update/delete in PostgreSQL by a database trigger. Transfers lock both accounts in primary-key order, reject negative or non-integer amounts, and append one debit and one credit in the same transaction. The reconciliation command fails with a non-zero global sum.

### Reserve report

- `reserve_report` appends an immutable daily snapshot. It sums positive current balances for `user_available`, `user_escrow`, `vendor_available`, `vendor_bond`, and `suspense` accounts; negative account balances and revenue/equity accounts are not counted as liabilities.
- Hot and cold reserve totals are configured as non-negative integer base units with `RESERVE_HOT_BALANCE_BASE_UNITS` and `RESERVE_COLD_BALANCE_BASE_UNITS`. The report ratio is `(hot + cold) / liabilities`. With no positive liabilities the ratio is not measurable, and no low-ratio warning is emitted.
- Ratios below 1.3:1 produce a warning log with the snapshot ID and component totals. The public `/reserves/` page displays the latest snapshot and paginated history. The history is an operational report; configured reserve balances are not independently audited.
- Run the `reserve_report` management command daily. `deploy/systemd/mk-reserve-report.timer` schedules it at 00:15 UTC. The matching service assumes the app is installed at `/opt/kola`, environment values are in `/opt/kola/.env`, and the `kola` system user owns the deployment.

### Per-chain reserve integrity

- `reserve_integrity` appends an immutable run every 15 minutes. On BTC, LTC, and TRC-20 it compares provider-reported native atomic wallet holdings against deposits in `SEEN`, `CONFIRMING`, or `CONFIRMED` state that have not been converted. Converted deposits are excluded.
- On XMR it compares total positive ledger liabilities against the reserve plus hot Monero balance, valued in base units at the lower of the freshest persisted XMR rates. Missing/stale rates and missing balance adapters are reported as unmeasurable, never as zero.
- A measurable shortfall greater than 1% of expected liability emits a critical alert and disables withdrawals. A surplus or shortfall at or below 1% does not automatically change the withdrawals switch; restoring withdrawals remains an explicit operator action.
- The public `/reserves/` page displays the latest per-chain coverage ratio, run time, balances, and unmeasurable chains. The existing aggregate daily reserve report remains separate.
- Install `deploy/systemd/mk-reserve-integrity.service` and `.timer` for the 15-minute run. Provider outages and malformed balance responses fail the run rather than being presented as zero.

### Operations dashboard and availability

- Staff can view `/ops/`, which shows current positive ledger liabilities, configured hot/cold reserve coverage, unresolved disputes, Redis withdrawal queue depth, and orders grouped by delivery city.
- If Redis is unavailable, the dashboard marks queue depth unavailable instead of displaying a false zero. `/health/` checks PostgreSQL and Redis and returns HTTP 503 when either dependency cannot be reached.
- `manage.py kill_withdrawals` pauses new withdrawal requests and worker sends. `manage.py kill_withdrawals --enable` restores them. `manage.py kill_new_orders` pauses all new `Order` inserts, including bulk inserts; `manage.py kill_new_orders --enable` restores order creation. Existing queued jobs remain queued while withdrawals are paused.
- The two switch states are persisted in the database and shown on the staff dashboard.
- `/canary/` displays the configured public statement, detached Ed25519 signature, and public key. Configure `CANARY_STATEMENT` and `CANARY_SIGNING_KEY`; the latter is a base64-encoded 32-byte private seed and must remain secret. The displayed signature is over the exact UTF-8 statement. Pin the public key independently of this page to verify identity. Without both settings the page clearly reports that the canary is not configured.

## Deposits and provider boundary

- One permanent address per user per chain, derived once when requested and reused.
- `ChainProvider` exposes address creation, inbound polling, atomic credit amount, decimal precision, and a read-only wallet-balance adapter. Providers without a balance adapter are explicitly unmeasurable. `FakeProvider` plus `manage.py fake_deposit` exercise the deposit path without network access.
- Every newly observed deposit is recorded as `SEEN`. The watcher promotes it to `CONFIRMING` and then `CONFIRMED` only when it reaches the chain's configured depth. `CREDITED` is the only credited deposit state; deposits in other states have no spendable-balance ledger posting.
- Deposit states are `SEEN`, `CONFIRMING`, `CONFIRMED`, `CREDITED`, `REVERSED`, and `ORPHANED`. State changes are recorded in the append-only deposit event history.
- Deposit conversion applies a 3% market commission, rounded up to the next base unit. A conversion is rejected if the commission would consume the entire gross amount; the deposit and rate quote remain unconsumed for reconciliation.
- If a credited transaction loses required depth or disappears from a provider snapshot declared complete, the deposit is reversed. Any amount that cannot be recovered from the user's available balance is recorded as a negative suspense balance (debt), not as a negative user balance. Providers that do not guarantee complete snapshots are not used to infer disappearance.
- TRC-20 promotion is limited to configured token contracts. For the configured Tether contract, each poll checks both sender and recipient against the contract blacklist; a blacklisted transfer cannot be confirmed or credited. A blacklist lookup failure fails the poll closed.
- Confirmed deposits remain unconverted until the account holder requests a quote. The quote uses the freshest two persisted rate ticks, is bound to the account and exact deposit amount, expires after 10 minutes, and can be used once. The account holder reviews the 3% fee and net base amount before confirming conversion.
- BTCPay uses a top-up invoice to obtain an on-chain destination and track invoice payments. The server may expire or retire that destination, so this adapter is best-effort rather than a guarantee of an indefinitely reusable address.
- Monero uses one hot-wallet RPC subaddress per user. Provision `MONERO_RESERVE_WALLET_RPC_URL` as a distinct view-only wallet endpoint. At production startup the app probes that endpoint for read access, and its reserve adapter permits only balance reads; the deployment must configure the underlying wallet as view-only. The hot wallet receives 15-minute sweeps from its known deposit subaddresses. The payout wallet is the only wallet RPC role allowed to broadcast withdrawals.
- Production Monero RPC settings use three distinct local wallet-RPC endpoints, each with separate credentials, and a local `MONEROD_RPC_URL`. Configure each wallet-RPC instance to use `http://127.0.0.1:18081` as its daemon address. Install `deploy/systemd/monerod.service` to run a local daemon with outbound peer traffic routed through the local Tor SOCKS listener; its `/etc/kola/monero.env` contains only `MONEROD_TOR_PROXY`. Production startup rejects a non-local monerod URL or Tor proxy.
- BTCPay exposes its configured store wallet balance; TronGrid reads `balanceOf(address)` for configured deposit addresses and allowlisted TRC-20 contracts. Address generation still requires a trusted local callable configured by `TRON_ADDRESS_DERIVER`, and every allowlisted contract must use the configured symbol and decimals.
- A withdrawal send is marked as started before the provider call. If its result is ambiguous, retries fail closed until an operator reconciles the send, preventing duplicate broadcasts. The Monero provider sends only through the payout wallet role.

### Payout address book

- Users may save, label, and soft-delete their own withdrawal addresses per supported chain. Saving requires the same address twice and server-side chain prefix/checksum validation.
- A newly saved address cannot be used for withdrawals for 24 hours. Withdrawal requests must resolve to an active address owned by that user and chain.
- Ownership verification is required before withdrawal and is currently available only for TRON addresses through a short-lived, single-use signed challenge. The verified marker is set only when the signature recovers the saved address; signature verification does not bypass the 24-hour lock. Other chain addresses cannot currently be used for withdrawals until a verification method is implemented.
- No JavaScript, wallet connection, private key, or seed phrase is used by this feature.

### User-linked non-custodial wallets

- Users may link multiple TRON/TRC-20 addresses to one Kola Market account. Linking requires a five-minute, single-use, account- and address-bound message signed by the wallet; signatures are verified server-side with the open-source TronPy library.
- The site stores public addresses and link/unlink timestamps only. It never requests or stores a seed phrase or private key, and a linked wallet cannot authorize deposits, withdrawals, or transactions.
- A linked address can be active on only one account at a time. Unlinking retains the association history. Wallet address ownership is proven at link time, not continuously monitored.
- This is a manual sign-and-submit flow, not WalletConnect: server-rendered pages and no client-side JavaScript remain in effect. Other chains require a separately implemented and tested signature standard before they can be linked.
- Linking an address does not conceal or make its on-chain activity non-traceable; it records an explicit association with the account.

## Rates and deposit conversion

- Use Coinbase and Kraken public rate sources per pair and take their integer median.
- Reject a trade when the sources diverge by more than 1%.
- Quotes lock for 10 minutes, are single-use, and are bound to a user and amount band. Store every quote permanently.
- Deposit conversion deducts a 3% commission, rounded up to the next base unit, and posts it to `market_fee`; the remainder is credited to the user's available balance.
- If a credited deposit is reversed, the user's net credit and its commission are reversed. Commission is recovered from `market_fee`, then `treasury` if already swept; any remaining shortfall is recorded in `suspense`.
- User-facing swaps are not implemented; rate quotes support conversion of confirmed deposits only.
- Rate requests are server-side, do not use API keys, and require `socks5h://` Tor transport. This hides the application origin from the feed endpoints; it does not make the activity untraceable.
- Pause swaps when either persisted source has not ticked in five minutes; do not quote from a stale feed. The watcher refreshes source ticks.

## User withdrawals

- Any authenticated user with spendable user or vendor balance may request a withdrawal to an active, verified payout address. Workflow: request → queue or manual approval → worker → status page.
- Configured hard limits: 2 `base` per transaction, 15 per hour, and 60 per day. Requests over a cap are queued for manual approval.
- Each request has an idempotency key and reserves the requested gross amount.
- Vendor bond is not withdrawable while any order or dispute is open.
- The commission is 3% of the gross amount, rounded up to the next base unit, and posted to `market_fee`. The provider receives the remaining net amount. Requests whose commission consumes the gross amount are rejected.
- A request reserves gross from positive `user_available` and/or `vendor_available` balances into the user's `user_escrow`. The Redis worker posts the net external transfer and commission only after the provider reports success. Reconciliation is checked before a request is queued and before it is sent.
- Staff may approve over-cap requests or reject them with a reason; rejection returns the reserved gross amount without charging commission.
- Financial jobs are persisted to the outbox and published after transaction commit; the worker claims outbox jobs using row locks and `SKIP LOCKED`.

## Fees

- Order fee: 4% of item total, deducted from vendor payout and posted to `market_fee`.
- Finalized order distribution: 95% to `vendor_available`, 4% to `market_fee`, and 1% to `treasury`, from `user_escrow`.
- Refunded orders pay no fee.
- A partial ruling charges the order fee only on the released portion.
- XMR multisig-funded orders are an explicit payment-method exception: after the confirmed XMR release reaches the platform wallet, credit 97% to `vendor_available` and the rounded-up 3% commission to `market_fee`. XMR refunds credit the buyer's internal balance with no commission. The platform bears XMR network fees and must not credit an underfunded settlement.
- Deposit conversion and withdrawals post a 3% gross-based commission, rounded up to the next base unit, to `market_fee`. Conversion credits net to `user_available`; withdrawal settlement sends net externally.
- The `sweep_market_fees` command moves positive `market_fee` and `market_spread` balances into `treasury` atomically. `deploy/systemd/mk-market-fee-sweep.timer` runs it daily at 00:20 UTC.

## Order state machine

Only the listed transitions are legal.

Checkout accepts a quantity only when the listing is active, its vendor is approved, and stock is sufficient. The stock reservation is atomic with order creation. Physical listings collect encrypted shipping address and phone; zone-restricted listings require the configured delivery zone. Digital listings are disabled: listing forms and services reject them, and public discovery and checkout hide legacy digital listings until a secure fulfillment flow exists. Buyers and vendors can see their orders at `/orders/`; buyers still fund a newly created order as a separate step.

The public catalog supports title/description substring search, category filtering, and newest/price sorting, with 25 results per page. Vendors can filter their own listings by active status and title.

Only the buyer of a finalized order may submit one 1–5-star review, with an optional comment up to 2,000 characters. Listing rating averages and counts are maintained when reviews are created or deleted; public listing pages link to paginated reviews.

Order, dispute, withdrawal, and vendor-approval events create in-app notifications for affected users. The shared header displays an unread count. Notifications are paginated; opening one marks it read and follows its related resource link, and users may mark all as read. No email is sent.

## Staff operations

- Staff can review all orders at `/ops/orders/`, filtering by status, city, and date range; results are paginated at 25 rows per page and link to order detail.
- Emergency order transitions require a reason and create an immutable audit record with staff actor, timestamp, previous state, and target state. A force action must not bypass escrow/ledger settlement; financially material transitions must use their normal domain settlement path or be unavailable as emergency overrides.
- Staff can activate/deactivate listings through a moderation-only interface. The moderation action cannot edit listing content or ownership; deactivated listings stop appearing in public search and category results immediately.
- `/ops/` shows aggregate order status counts and finalized GMV, order volume by city, top vendors/listings, dispute counts/outcomes, and 30-day deposit/withdrawal volumes by chain. Analytics are database aggregates, not per-row loops.
- Staff can pause/resume configured market switches with a required reason. Each change records the actor, changed setting, effective value, time, and reason.

## Provider polling and capabilities

- Each chain provider explicitly declares whether it supports deposits, withdrawals, and balance queries. A service checks the capability before creating a deposit address or reserving funds for a withdrawal and reports unsupported operations clearly.
- TronGrid transfer polling follows all provider cursor pages for a block range and advances a persisted provider/chain block watermark only after a successful complete poll. The poll resumes from the next unprocessed block. Transient provider errors use bounded exponential backoff; after retries are exhausted, the cycle logs an error and does not advance the watermark.

## Deployment and recovery

- The web process runs under systemd/Gunicorn on the configured private listener. Background workers/timers and monitoring use checked-in systemd units.
- Database backups are encrypted before off-host upload, checksum-verified, and removed from local staging only after upload verification succeeds. Encryption recipients/keys and remote storage configuration are supplied by deployment environment, never committed.
- Restore is a manual, operator-controlled process and must be tested against an isolated database before use in recovery.
- CI provisions PostgreSQL and Redis and runs Django checks, the pytest suite, and migration drift checks.
- Health monitoring reports dependency status and supported operational signals (latest scheduler/deposit poll, queue depth, and database connection diagnostics); unavailable metrics are reported as unavailable rather than fabricated.

The default payment method is the internal marketplace ledger. Buyers may instead request XMR multisig funding for a draft order. An independently deployed signer gateway coordinates buyer, vendor, and mediator wallet setup and returns the multisig address; Kola locks an XMR/base quote when setup is ready. Confirmed funding advances the order without a ledger escrow posting. Release, refund, and partial settlement are proposals that remain pending until the gateway reports a participant-approved, confirmed spend to the platform wallet. Kola then credits vendor/buyer ledger balances. The gateway must enforce 2-of-3 signatures and never treat Kola's service credential as participant approval. It must not auto-sign after silence; Monero has no native time lock.

| From | To | Actor or trigger | Ledger posting |
|---|---|---|---|
| `DRAFT` | `FUNDED` | Buyer | `user_available → user_escrow` |
| `DRAFT` | `EXPIRED` | Timer, 30 minutes | None |
| `DRAFT` | `CANCELLED` | Buyer | None |
| `DRAFT` | `SETTLEMENT_PENDING` | Late XMR funding after cancellation/expiry | Await participant-approved refund |
| `FUNDED` | `ACCEPTED` | Vendor | None |
| `FUNDED` | `REFUNDED` | Vendor rejects or 12-hour timeout | `user_escrow → user_available` |
| `FUNDED` | `SETTLEMENT_PENDING` | XMR vendor rejection or response deadline | Await participant-approved refund |
| `ACCEPTED` | `PACKED` | Vendor | None |
| `PACKED` | `DISPATCHED` | Vendor | None |
| `DISPATCHED` | `DELIVERED` | Proof-of-delivery token | None |
| `ACCEPTED` | `DELIVERED` | Digital delivery file post | None |
| `DELIVERED` | `FINALIZED` | Timer: 2 hours digital, 24 hours city, 7 days domestic post, 14 days cross-border | `user_escrow → vendor_available` (95%), `market_fee` (4%), and `treasury` (1%) |
| `DELIVERED` | `SETTLEMENT_PENDING` | XMR release timer | Await 2-of-3-approved release |
| `DISPATCHED` | `DISPUTED` | Buyer | None |
| `DELIVERED` | `DISPUTED` | Buyer, before finalization | None |
| `DISPUTED` | `FINALIZED` | Admin ruling | Same distribution as normal finalization |
| `DISPUTED` | `REFUNDED` | Admin ruling | `user_escrow → user_available` |
| `DISPUTED` | `PARTIAL` | Admin split ruling | Split pro rata across the finalization and refund postings |
| `DISPUTED` | `SETTLEMENT_PENDING` | XMR admin ruling | Await participant-approved release/refund proposal |
| `SETTLEMENT_PENDING` | `FINALIZED` / `REFUNDED` / `PARTIAL` | Confirmed signer-gateway callback | Credit internal balances only after confirmed platform-wallet receipt |

Digital orders skip `PACKED` and `DISPATCHED`; delivery is recorded on file post. A buyer may extend the finalization timer twice by 24 hours each, before expiry. Nothing transitions after `FINALIZED` or `REFUNDED`.

### Delivery and disputes

- Cities own named delivery zones; a city may have multiple zones.
- Orders may store a courier reference and private pack photo. Pack photos and dispute attachments are written under `MEDIA_ROOT` with random filenames and are not exposed through public media URLs. Pack photos accept validated JPG, PNG, or WebP images up to 10 MB. Evidence attachments accept PDF, JPG, PNG, or WebP up to 10 MB.
- Dispatch generates a random bearer proof-of-delivery token. Only its SHA-256 digest and a six-hour expiry are stored; the raw token is shown once to the vendor after dispatch. A valid unexpired token marks delivery and is consumed.
- Order shipping address and phone use authenticated Fernet encryption at the database field layer. Configure `FIELD_ENCRYPTION_KEY` before applying migrations or using these fields. It is a separately generated deployment secret, not derived from the Django secret key. Losing or rotating the key without re-encryption makes stored contact fields unreadable. Back it up securely and keep it out of source control.
- Dispute attachments and reasons are private to the participants and staff. Evidence downloads require staff authentication.
- A public ruling contains only a numeric `min-max base` amount band, the order listing category, and the outcome; it does not contain names, dispute reasons, free text, or attachments. For a partial outcome, the admin supplies a released amount in base units; that amount and the refund remainder are settled from escrow in the same transaction, while the public ruling still exposes only its outcome.
- XMR multisig depends on an independently deployed signer gateway and is unavailable until `docs/MONERO_MULTISIG_ESCROW.md`'s API, signer authorization, and stagenet requirements are met. Multisig assets and outstanding XMR order liabilities are included in reserve-integrity accounting. A missing gateway balance adapter makes XMR reserve coverage unmeasurable.

## Evidence, disputes, and authority

- The admin is the sole dispute authority. Target ruling SLA: 72 hours.
- Rulings are public and include only amount band, category, and ruling; they contain no names.
- Evidence is mandatory and typed. Buyer evidence contains a reference code, timestamp, sending number, and amount. Vendor evidence is an app statement covering the relevant period.
- The party whose evidence fails to reconcile loses.
- A faked reference code results in a permanent ban and bond slashing.
- After three false disputes, a buyer is rate-limited to one open order.

## Authentication

- There is no email-based recovery flow.
- Use username and password authentication followed by an OpenPGP detached-signature challenge for every account. Never store private keys.
- New accounts enroll a public key by signing a fresh challenge. Existing accounts must complete one password-authenticated enrollment before receiving an authenticated session.
- Generate 10 single-use recovery codes when a key is enrolled, hash them at rest, and show them once. A logged-in user can regenerate them only after a fresh OpenPGP challenge.
- Require the exact configured v3 onion host for every production request; production startup fails without a valid onion host and a unique Django secret key.
- Use GnuPG for signature verification in an isolated temporary keyring; install the `gnupg` system package on the web host.
- Use Argon2 password hashing and a Redis-backed login rate limit.
- Allow session durations of 30 minutes, 1 hour, or 2 hours; default to 30 minutes.
- The initial login throttle allows five failed attempts per username/IP key per 15-minute window.
- Site identity uses CSS-rendered initials, never user-uploaded profile photos. The initials are the username's first character uppercased and second character lowercased (a single-character name repeats its first character in lowercase). Colors distinguish customer, vendor, delivery, and admin roles; delivery users are identified by membership in the `delivery` group.

## Deployment

- One Ubuntu 24.04 LTS VPS, 4 GB RAM, EU region, paid in crypto.
- PostgreSQL and Redis bind to localhost only.
- Run three systemd units: `mk-web` (Gunicorn on `127.0.0.1:8000`), `mk-worker`, and `mk-watcher`.
- An onion service maps port 80 to the Gunicorn port. No TLS, CDN, or external assets.
- Nightly `pg_dump` is piped through `age` to a second provider.
- Set `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY` to a unique secret of at least 50 characters, and `DJANGO_ONION_HOSTS` to exact v3 `.onion` hostnames. The app derives `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from that list and rejects other Host values.
- `SESSION_COOKIE_SECURE=false` is allowed only for the HTTP onion service; keep the web listener private behind Tor. `SESSION_COOKIE_HTTPONLY=true`, `SESSION_COOKIE_SAMESITE=Lax`, and session expiry is 30 minutes.

## Exact dependency pins

The selected patches are the newest available in the requested version families at setup:

| Package | Pin |
|---|---|
| Django | `5.1.15` |
| psycopg[binary] | `3.2.13` |
| redis | `5.3.1` |
| gunicorn | `23.0.0` |
| argon2-cffi | `23.1.0` |
| Pillow | `11.3.0` |
| python-dotenv | `1.2.4` |
| TronPy | `0.7.0` |
| requests | `2.32.5` |
| PySocks | `1.7.1` |
| pytest | `8.4.2` |
| pytest-django | `4.9.0` |

## Step-one configuration and unresolved details

- Django reads PostgreSQL, Redis queue, host, CSRF, session, and secret settings from environment variables. `.env.example` is a local template; its development key must be replaced for deployment.
- The project skeleton registers the requested apps and prepares `core/services/`; models, service implementations, provider code, and migrations are not part of step 1.
- Quote amount bands are supplied at quote request and checked against the exact deposit amount. The TRON address deriver is an operator-supplied local callable; no private key derivation seed is embedded in the application.
- Values not specified in the brief, including bond slash amounts, remain unset rather than inferred.
- The requested Django 5.1 series is followed as specified. Its newest patch is pinned; confirm support policy before production deployment.
- Real chain deposits require provider-specific secrets and configuration; real withdrawals are deliberately unavailable until an idempotent send implementation is enabled and tested.
