# Kola Market — Codebase Audit

**Audit basis:** source, templates, settings, migrations, tests, and deployment files in this workspace. Paths are relative to the repository root and link to the inspected files. This is a static-code audit, not a live-provider or production deployment certification.

**Executive summary:** Kola is a server-rendered Django marketplace with PGP-backed accounts, vendor listings, catalog search, buyer reviews, in-app notifications, atomic stock reservation and checkout, buyer/vendor order history, an append-only ledger, deposit and withdrawal screens, escrow/disputes, reserve monitoring, and staff operations. It has no persisted cart or user-to-user messaging. Deposits and withdrawals apply a 3% gross-based commission rounded up to a base unit. This is a source audit, not a production or live-provider certification.

## 0. Evidence and verification limits

- Product intent is described in [`docs/SPEC.md`](./SPEC.md); conventions are in [`CONVENTIONS.md`](../CONVENTIONS.md).
- `./.venv/bin/python manage.py check` passed: **no issues**.
- Verification limits for this workspace are recorded in [`docs/codebase/TESTING.md`](codebase/TESTING.md).
- No live chain providers, Tor, Redis, or production host were exercised. No Git history was available in this workspace, so churn and recent-change claims are omitted.
- `.env` was not read. Configuration findings use [`mk/settings.py`](../mk/settings.py) and [`.env.example`](../.env.example).

## 1. Pages, screens, routes, and access

The root URL configuration includes account, catalog, order, and operations routes plus Django admin and a stylesheet endpoint. `/` redirects to `/catalog/`. Server-rendered HTML is used throughout; there is no frontend component framework.

### Global routes

| Route | Component / result | Access | Notes |
|---|---|---|---|
| `/static/css/site.css` | `core.static_views.site_stylesheet` | Public | Serves the one project stylesheet. |
| `/admin/` | Django Admin (`PGPAdminSite`) | Staff; PGP-verified session | Custom admin site sends login to the account flow. |
| `/` | `RedirectView` | Public | Permanent redirect (301) to `/catalog/`. |
| unmatched URL | `page_not_found` — `404.html` | Public | Branded project 404 page. |
| unhandled exception | `server_error` — `500.html` | Public | Branded production-safe 500 page; does not display exception details. |

Sources: [`mk/urls.py`](../mk/urls.py), [`core/static_views.py`](../core/static_views.py), [`accounts/admin_site.py`](../accounts/admin_site.py), [`orders/templates/orders/action_error.html`](../orders/templates/orders/action_error.html), [`accounts/templates/accounts/_site_header.html`](../accounts/templates/accounts/_site_header.html).

### Account routes

| Route | View / screen | Access | Methods / behavior |
|---|---|---|---|
| `/accounts/register/` | `register_view` — `register.html` | Public | GET/POST; creates account then starts PGP enrollment. |
| `/accounts/login/` | `login_view` — `login.html` | Public | GET/POST; password step and rate limit. |
| `/accounts/pgp-auth/` | `pgp_auth_view` — `pgp_auth.html` or `pgp_recovery_codes.html` | Pending challenge session; regeneration also requires logged-in owner | GET/POST; enroll, sign in, use recovery code, or regenerate codes. |
| `/accounts/logout/` | `logout_view` | Public POST action | Logs out and redirects to login. |
| `/accounts/profile/` | `profile_view` — `profile.html` | Authenticated | GET/POST. |
| `/accounts/profile/deposits/` | `deposit_addresses_view` — `deposits.html` | Authenticated | GET; lists permanent addresses, available balance, and recent deposits. |
| `/accounts/profile/deposits/new/` | `deposit_address_create` | Authenticated POST action | Creates or reuses one address per chain. |
| `/accounts/profile/deposits/history/` | `deposit_history` — `deposit_history.html` | Authenticated | GET; paginated. |
| `/accounts/profile/withdrawals/` | `withdrawal_history_view` — `withdrawals.html` | Authenticated | GET/POST; request form and paginated history. |
| `/accounts/profile/withdrawals/<withdrawal_id>/` | `withdrawal_detail_view` — `withdrawal_detail.html` | Authenticated owner only | GET; current status, fee, net amount, provider reference, or rejection reason. |
| `/accounts/profile/wallets/` | `wallets_view` — `wallets.html` | Authenticated | GET. |
| `/accounts/profile/wallets/challenge/` | `wallet_challenge_start_view` | Authenticated POST action | Starts TRON address challenge. |
| `/accounts/profile/wallets/challenge/<challenge_id>/` | `wallet_challenge_view` — `wallet_challenge.html` | Authenticated; own challenge only | GET/POST. |
| `/accounts/profile/wallets/<wallet_id>/unlink/` | `unlink_wallet_view` | Authenticated POST action | Soft-unlinks own wallet. |
| `/accounts/profile/payout-addresses/` | `payout_addresses_view` — `payout_addresses.html` | Authenticated | GET. |
| `/accounts/profile/payout-addresses/save/` | `payout_address_save_view` | Authenticated POST action | Saves own validated address. |
| `/accounts/profile/payout-addresses/<payout_address_id>/delete/` | `payout_address_delete_view` | Authenticated POST action | Soft-deletes own address. |
| `/accounts/profile/payout-addresses/<payout_address_id>/verify/` | `payout_address_verify_start_view` | Authenticated POST action | Starts required-before-withdrawal TRON verification. |
| `/accounts/profile/payout-addresses/verify/<challenge_id>/` | `payout_address_verify_view` — `payout_address_verify.html` | Authenticated; own challenge only | GET/POST. |
| `/accounts/profile/recovery-codes/` | `regenerate_recovery_codes_view` | Authenticated POST action | Starts fresh PGP challenge. |

Sources: [`accounts/urls.py`](../accounts/urls.py), [`accounts/views.py`](../accounts/views.py), [`accounts/forms.py`](../accounts/forms.py).

### Catalog and vendor routes

| Route | View / screen | Access | Methods / behavior |
|---|---|---|---|
| `/catalog/` | `category_list` — `category_list.html` | Public | Renders categories with active approved-vendor listings. |
| `/catalog/search/` | `catalog_search` — `search_results.html` | Public | GET title/description substring search, optional category, newest/price sort, 25 per page. |
| `/catalog/categories/<slug>/` | `category_detail` — `category_detail.html` | Public | Renders active listings; 25 per page. |
| `/catalog/listings/<listing_id>/` | `listing_detail` — `listing_detail.html` | Public | Active approved-vendor listing detail; authenticated buyers can continue to checkout. |
| `/catalog/listings/<listing_id>/reviews/` | `listing_reviews` — `listing_reviews.html` | Public | Public listing reviews, 10 per page. |
| `/catalog/listings/<listing_id>/checkout/` | `checkout_view` — `checkout.html` | Authenticated | GET/POST; validates shipping/zone/quantity and creates an order while reserving stock. |
| `/catalog/vendor/` | `vendor_dashboard` — `vendor_apply.html` or `vendor_dashboard.html` | Authenticated | GET/POST; blank application POST creates pending vendor profile; approved vendors may filter own listings by status/title. |
| `/catalog/vendor/listings/new/` | `listing_create` — `listing_form.html` | Authenticated; service requires approved vendor | GET/POST. |
| `/catalog/vendor/listings/<listing_id>/edit/` | `listing_edit` — `listing_form.html` | Authenticated owner; approved vendor | GET/POST. |
| `/catalog/vendor/listings/<listing_id>/delete/` | `listing_delete` | Authenticated; owner check in service | POST. |
| `/catalog/admin/vendors/` | `vendor_approval_queue` — `vendor_approval_queue.html` | Staff only | Queue page. |
| `/catalog/admin/vendors/<profile_id>/approve/` | `vendor_approve` | Staff only | POST. |

Sources: [`catalog/urls.py`](../catalog/urls.py), [`catalog/views.py`](../catalog/views.py), [`catalog/forms.py`](../catalog/forms.py), [`core/services/save_listing.py`](../core/services/save_listing.py).

### Orders and dispute routes

| Route | View / screen | Access | Methods / behavior |
|---|---|---|---|
| `/orders/` | `order_history` — `history.html` | Authenticated buyer or vendor | GET; combined role-aware history, 25 per page. |
| `/orders/rulings/` | `public_rulings` — `public_rulings.html` | Public | Paginated rulings. |
| `/orders/rulings/<ruling_id>/` | `public_ruling_detail` — `public_ruling_detail.html` | Public | Public ruling detail. |
| `/orders/review/` | `dispute_queue` — `dispute_queue.html` | Staff only | Open dispute queue, 25 per page. |
| `/orders/review/<dispute_id>/` | `review_dispute` — `review_dispute.html` | Staff only | GET/POST; review and publish ruling. |
| `/orders/evidence/<evidence_id>/download/` | `evidence_download` | Staff only | GET attachment download. |
| `/orders/<order_id>/` | `order_detail` — `detail.html` | Authenticated buyer or vendor participant | GET; participants only. |
| `/orders/<order_id>/review/` | `submit_review_view` | Authenticated buyer of a finalized order | POST; one review per order. |
| `/orders/<order_id>/pack/` | `pack_order_view` | Authenticated vendor participant | POST photo upload. |
| `/orders/<order_id>/dispatch/` | `dispatch_order_view` | Authenticated vendor participant | POST courier reference; returns one-time token to vendor session. |
| `/orders/<order_id>/deliver/` | `record_delivery_view` | **Unauthenticated bearer-token** | POST; the hashed, expiring proof-of-delivery token is the credential. |
| `/orders/<order_id>/dispute/` | `open_dispute_view` | Authenticated buyer | POST. |
| `/orders/dispute/<dispute_id>/evidence/` | `submit_dispute_evidence_view` | Authenticated dispute participant | POST. |
| `/orders/<order_id>/fund/` | `fund_order_view` | Authenticated buyer | POST. |
| `/orders/<order_id>/monero-escrow/` | `start_monero_escrow_view` | Authenticated buyer | POST; requests a multisig escrow through the configured independent signer gateway. |
| `/orders/<order_id>/cancel/` | `cancel_order_view` | Authenticated buyer | POST. |
| `/orders/<order_id>/accept/` | `accept_order_view` | Authenticated vendor participant | POST. |
| `/orders/<order_id>/reject/` | `reject_order_view` | Authenticated vendor participant | POST. |
| `/orders/<order_id>/extend-finalize/` | `extend_finalize_view` | Authenticated buyer | POST. |
| `/payments/monero-escrow/events/` | `monero_escrow_callback` | Signed gateway callback | POST JSON; timestamped HMAC, event idempotency, and sequence validation. |
| `/notifications/` | `notification_list` — `notifications.html` | Authenticated | GET; paginated list of recipient-owned notifications. |
| `/notifications/<notification_id>/` | `open_notification` | Authenticated; notification owner only | GET; marks read and redirects to related resource. |
| `/notifications/mark-all-read/` | `mark_notifications_read` | Authenticated | POST; marks all recipient-owned notifications read. |

Sources: [`orders/urls.py`](../orders/urls.py), [`orders/views.py`](../orders/views.py), [`core/services/order_transitions.py`](../core/services/order_transitions.py).

### Operations routes

| Route | View / screen | Access | Methods / behavior |
|---|---|---|---|
| `/ops/` | `admin_dashboard` — `admin_dashboard.html` | Staff only | Aggregated order/payment/dispute/reserve metrics and reason-required market-switch forms. |
| `/ops/orders/` | `order_list` — `order_list.html` | Staff only | GET status/city/date filters, 25 orders per page. |
| `/ops/orders/<order_id>/force-transition/` | `order_force_transition` | Staff-only POST action | Only safe `FUNDED` → `ACCEPTED` override is offered; requires a reason and immutable audit log. |
| `/ops/market-switch/<feature>/toggle/` | `market_switch_toggle` | Staff-only POST action | Toggles one known market switch; reason required and audit logged. |
| `/ops/withdrawals/` | `withdrawal_approval_queue` — `withdrawal_approval.html` | Staff only | Pending manual approval queue, 25 per page. |
| `/ops/withdrawals/<withdrawal_id>/approve/` | `withdrawal_approve` | Staff-only POST action | Approves and enqueues after transaction commit. |
| `/ops/withdrawals/<withdrawal_id>/reject/` | `withdrawal_reject` | Staff-only POST action | Requires a reason and returns reserved gross without charging commission. |
| `/reserves/` | `reserve_history` — `reserve_history.html` | Public | Aggregate snapshots, per-chain latest run, paginated history (50/page). |
| `/canary/` | `public_canary` — `canary.html` | Public | Signed statement or explicit unconfigured state. |
| `/health/` | `health` | Public | JSON PostgreSQL/Redis status, queue depth, connection counts and unavailable scheduler/deposit-poll timestamps; 503 if a dependency fails. |

Sources: [`ops/urls.py`](../ops/urls.py), [`ops/views.py`](../ops/views.py), [`ops/templates/ops/reserve_history.html`](../ops/templates/ops/reserve_history.html).

### Page/component file inventory

The page templates and shared partials are enumerated below. Django view functions listed in §1 are the server-side page components. POST-only action endpoints generally render an associated form or redirect rather than owning a separate page.

| Route | View component | Template/component file |
|---|---|---|
| `/accounts/register/` | `register_view` | [`accounts/templates/accounts/register.html`](../accounts/templates/accounts/register.html) |
| `/accounts/login/` | `login_view` | [`accounts/templates/accounts/login.html`](../accounts/templates/accounts/login.html) |
| `/accounts/pgp-auth/` | `pgp_auth_view` | [`accounts/templates/accounts/pgp_auth.html`](../accounts/templates/accounts/pgp_auth.html); success/recovery codes: [`accounts/templates/accounts/pgp_recovery_codes.html`](../accounts/templates/accounts/pgp_recovery_codes.html) |
| `/accounts/profile/` | `profile_view` | [`accounts/templates/accounts/profile.html`](../accounts/templates/accounts/profile.html) |
| unmatched URL | `page_not_found` | [`mk/templates/404.html`](../mk/templates/404.html) |
| unhandled exception | `server_error` | [`mk/templates/500.html`](../mk/templates/500.html) |
| `/accounts/profile/deposits/` | `deposit_addresses_view` | [`accounts/templates/accounts/deposits.html`](../accounts/templates/accounts/deposits.html) |
| `/accounts/profile/deposits/history/` | `deposit_history` | [`accounts/templates/accounts/deposit_history.html`](../accounts/templates/accounts/deposit_history.html) |
| `/accounts/profile/withdrawals/` | `withdrawal_history_view` | [`accounts/templates/accounts/withdrawals.html`](../accounts/templates/accounts/withdrawals.html) |
| `/accounts/profile/withdrawals/<withdrawal_id>/` | `withdrawal_detail_view` | [`accounts/templates/accounts/withdrawal_detail.html`](../accounts/templates/accounts/withdrawal_detail.html) |
| `/accounts/profile/wallets/` | `wallets_view` | [`accounts/templates/accounts/wallets.html`](../accounts/templates/accounts/wallets.html) |
| `/accounts/profile/wallets/challenge/<challenge_id>/` | `wallet_challenge_view` | [`accounts/templates/accounts/wallet_challenge.html`](../accounts/templates/accounts/wallet_challenge.html) |
| `/accounts/profile/payout-addresses/` | `payout_addresses_view` | [`accounts/templates/accounts/payout_addresses.html`](../accounts/templates/accounts/payout_addresses.html) |
| `/accounts/profile/payout-addresses/verify/<challenge_id>/` | `payout_address_verify_view` | [`accounts/templates/accounts/payout_address_verify.html`](../accounts/templates/accounts/payout_address_verify.html) |
| `/catalog/` | `category_list` | [`catalog/templates/catalog/category_list.html`](../catalog/templates/catalog/category_list.html) |
| `/catalog/search/` | `catalog_search` | [`catalog/templates/catalog/search_results.html`](../catalog/templates/catalog/search_results.html) |
| `/catalog/categories/<slug>/` | `category_detail` | [`catalog/templates/catalog/category_detail.html`](../catalog/templates/catalog/category_detail.html) |
| `/catalog/listings/<listing_id>/` | `listing_detail` | [`catalog/templates/catalog/listing_detail.html`](../catalog/templates/catalog/listing_detail.html) |
| `/catalog/listings/<listing_id>/reviews/` | `listing_reviews` | [`catalog/templates/catalog/listing_reviews.html`](../catalog/templates/catalog/listing_reviews.html) |
| `/catalog/listings/<listing_id>/checkout/` | `checkout_view` | [`catalog/templates/catalog/checkout.html`](../catalog/templates/catalog/checkout.html) |
| `/catalog/vendor/` | `vendor_dashboard` | [`catalog/templates/catalog/vendor_apply.html`](../catalog/templates/catalog/vendor_apply.html) or [`catalog/templates/catalog/vendor_dashboard.html`](../catalog/templates/catalog/vendor_dashboard.html) |
| `/catalog/vendor/listings/new/`, `/catalog/vendor/listings/<listing_id>/edit/` | `listing_create`, `listing_edit` | [`catalog/templates/catalog/listing_form.html`](../catalog/templates/catalog/listing_form.html) |
| `/catalog/admin/vendors/` | `vendor_approval_queue` | [`catalog/templates/catalog/vendor_approval_queue.html`](../catalog/templates/catalog/vendor_approval_queue.html) |
| `/orders/<order_id>/` | `order_detail` | [`orders/templates/orders/detail.html`](../orders/templates/orders/detail.html) |
| `/orders/<order_id>/review/` | `submit_review_view` | Inline form in [`orders/templates/orders/detail.html`](../orders/templates/orders/detail.html) |
| `/orders/` | `order_history` | [`orders/templates/orders/history.html`](../orders/templates/orders/history.html) |
| `/orders/<order_id>/*` and `/orders/dispute/<dispute_id>/evidence/` | Order action views | [`orders/templates/orders/action_error.html`](../orders/templates/orders/action_error.html) for action errors; successful actions redirect to order detail. |
| `/orders/rulings/` | `public_rulings` | [`orders/templates/orders/public_rulings.html`](../orders/templates/orders/public_rulings.html) |
| `/orders/rulings/<ruling_id>/` | `public_ruling_detail` | [`orders/templates/orders/public_ruling_detail.html`](../orders/templates/orders/public_ruling_detail.html) |
| `/orders/review/` | `dispute_queue` | [`orders/templates/orders/dispute_queue.html`](../orders/templates/orders/dispute_queue.html) |
| `/orders/review/<dispute_id>/` | `review_dispute` | [`orders/templates/orders/review_dispute.html`](../orders/templates/orders/review_dispute.html) |
| `/notifications/` | `notification_list` | [`core/templates/core/notifications.html`](../core/templates/core/notifications.html); authenticated, 25 per page |
| `/notifications/<notification_id>/` | `open_notification` | Authenticated notification owner; marks read and redirects to related resource |
| `/notifications/mark-all-read/` | `mark_notifications_read` | Authenticated POST; marks all of the user's unread items read |
| `/ops/` | `admin_dashboard` | [`ops/templates/ops/admin_dashboard.html`](../ops/templates/ops/admin_dashboard.html) |
| `/ops/withdrawals/` | `withdrawal_approval_queue` | [`ops/templates/ops/withdrawal_approval.html`](../ops/templates/ops/withdrawal_approval.html) |
| `/reserves/` | `reserve_history` | [`ops/templates/ops/reserve_history.html`](../ops/templates/ops/reserve_history.html) |
| `/canary/` | `public_canary` | [`ops/templates/ops/canary.html`](../ops/templates/ops/canary.html) |
| All screens using the shared site chrome | Shared include | [`accounts/templates/accounts/_site_header.html`](../accounts/templates/accounts/_site_header.html) |

Other components are Django admin screens (`accounts/admin.py`, `catalog/admin.py`, `orders/admin.py`), CLI management commands, and service functions. There are no React/Vue/Angular page components.

### Dead, unlinked, or orphaned surfaces

- `/` redirects to `/catalog/`; the action-error link and project-owned 404/500 pages are defined.
- The order history and purchase entry points now link from the shared header/listing detail. Public ruling routes remain directly reachable but are not prominent in the shared navigation.
- [`ledger/views.py`](../ledger/views.py) remains a placeholder module and is not routed.
- No project-owned route declaration was found that is omitted from the root URL includes.

## 2. User-facing and system processes

| Process | Implemented path | Status |
|---|---|---|
| Registration | Registration form → `register_user` password validation/save → short-lived PGP enrollment challenge → isolated GnuPG signature check → 10 hashed single-use recovery codes shown once → authenticated session. | **Complete in source**, configuration requires PostgreSQL, Redis, Argon2, and GnuPG. No email. |
| Login / recovery / logout | Username/password → atomic Redis failed-attempt check/increment → PGP detached signature or one recovery code → session; profile can regenerate codes through a new PGP challenge; logout is POST. | **Complete in source.** No password reset/recovery email, intentionally absent per spec. |
| Profile and wallets | Set one of three session lengths; manually paste TRON address; server challenge bound to account/address/nonce/expiry; verify signature; retain link/unlink history. | **Complete for TRON**, no other chains, no WalletConnect or funds authority. |
| Payout address book | Select chain → type address twice → server prefix/checksum normalization and equality → 24-hour lock → 5-minute TRON signature ownership proof → soft delete. | **Address-book flow complete.** Withdrawals require a verified address; the verification flow currently supports TRON only. |
| Browse and search catalog | Category list or title/description search → optional category filter and newest/price sort → paginated active listings from approved vendors → listing detail and public paginated reviews. | **Implemented.** Search is substring-based; there is no persisted cart. |
| Vendor onboarding/listing | Authenticated user POSTs blank application → pending profile and vendor bond ledger account → staff approval queue → staff approval → approved vendor creates/edits/deletes listings. | **Implemented.** Bond funding/adjustment is not exposed and is called out as unimplemented in the spec. |
| Create order / cart / checkout | Authenticated buyer opens listing checkout → server validates listing/vendor/stock, shipping mode and delivery zone → atomic stock reservation and `Order` creation → order detail. | **Implemented.** There is no persisted cart; buyer funding remains a separate order action. |
| Order history | Authenticated buyer or vendor opens `/orders/`; role-aware orders are listed newest-first with pagination. | **Implemented and linked from the shared header.** |
| Order escrow and fulfillment | Checkout-created physical order → buyer funds from available to escrow → vendor accepts/rejects → pack/upload → dispatch/token → bearer-token delivery → scheduled finalization; buyer can dispute or extend twice. | **Physical flow implemented.** Digital listing creation, discovery, and checkout are disabled until secure fulfillment exists; a legacy transition exists but is not a digital file handoff. |
| Order expiry/finalization | `run_scheduler` expires draft/funded orders, finalizes delivered orders, and deletes expired unused quotes; systemd timer invokes it every minute. | **Implemented in source/deployment files.** |
| Disputes and ruling | Buyer disputes with mandatory evidence → participants add evidence → staff queue/review → staff rules release/refund/partial → escrow settlement → public ruling lists amount band/category/outcome only. | **Implemented for ordinary orders.** Notifications are created for dispute opening and ruling; no defined 72-hour enforcement/alert. |
| Reviews | Buyer submits one 1–5-star review after finalization → listing aggregates are recomputed → public listing review page shows paginated comments. | **Implemented in source.** Buyer ownership and finalized status are service-enforced; database uniqueness prevents a second review per order. |
| In-app notifications | Order, dispute, withdrawal, and vendor events create recipient-scoped rows → shared header shows unread count → user opens and marks individual item read or marks all read. | **Implemented in source.** Includes order cancellation/expiry and Monero settlement progress; no email is sent. |
| Deposits / conversion | User requests/reuses a deposit address and views recent/history rows; watcher captures rates, applies confirmation depth and chain rules, converts gross amount to 97% user credit plus rounded-up 3% market fee, and reverses eligible credited deposits. | **Implemented in source.** Live provider and chain behavior were not exercised. |
| Withdrawals | User with spendable user/vendor balance selects an active verified payout address and requests gross amount; 3% (rounded up) is reserved as market fee and net is sent by worker; over-cap requests wait in staff queue; rejection refunds gross with a reason. | **Implemented in source.** Address verification is currently TRON-only; live providers and staff browser workflows were not exercised. |
| Messaging/notifications | No buyer/vendor chat or inbox is present. In-app event notifications are implemented through `core.Notification`; SMTP/email notification delivery is intentionally absent. | **Partial:** in-app notifications exist; user-to-user messaging and email do not. |
| Admin / operations | Django admin supports staff user/category/city/zone management and listing activation moderation; vendor approval, dispute rulings, order listing/detail and limited safe transition, pending withdrawal approval/rejection, analytics, and audited kill-switch toggles are staff screens. | **Implemented in source.** The emergency order override is deliberately limited to `FUNDED` → `ACCEPTED`; the dashboards and transitions have not been database-tested in this workspace. |
| Reserves / health / canary | Daily aggregate reserve snapshots; 15-minute per-chain check; >1% measurable shortfall disables withdrawals; public history and status; health JSON checks DB/Redis, reports queue depth and DB connection information, and marks scheduler/deposit-poll timestamps unavailable where no durable source exists; canary signs configured statement. | **Implemented in code and systemd units**, not live-tested here. Public aggregate reserve numbers are operator-configured, not independently audited. |

Key source: [`core/services/`](../core/services/), [`payments/providers/`](../payments/providers/), [`payments/management/commands/`](../payments/management/commands/), [`orders/management/commands/run_scheduler.py`](../orders/management/commands/run_scheduler.py), [`deploy/systemd/`](../deploy/systemd/).

## 3. Forms and input validation

All listed app forms submit ordinary POST requests, not JSON APIs. Django form validation runs server-side. Where templates use `form.as_p`, Django emits labels, errors, and browser validation attributes derived from the form fields. Custom hand-written markup adds some `required`, `maxlength`, and file `accept` attributes; browser constraints are not a substitute for server validation.

### Fielded application forms

| Form / component | Fields (type; required; max; validation) | Submit endpoint | Error handling |
|---|---|---|---|
| [`RegistrationForm`](../accounts/forms.py) — `register.html` | `username` text; required; 150; NFKC normalization and unique username check. `password1`, `password2` password; required; no app-specific max; Django password validators (similarity, minimum length, common, numeric) and match check. | `POST /accounts/register/` | Form errors; service validation attached to form. Next step is PGP enrollment. |
| [`LoginForm`](../accounts/forms.py) — `login.html` | `username` text; required; 150. `password` password; required; no explicit max. | `POST /accounts/login/` | Invalid credentials form error; rate limit gives 429/banner. Redis connectivity errors are not explicitly caught. |
| [`PGPEnrollmentForm`](../accounts/forms.py) — `pgp_auth.html` | `public_key` textarea; required; 131,072; ASCII/armored key, one primary key, GnuPG signature verification. `signature` textarea; required; 32,768; armored detached signature over challenge. | `POST /accounts/pgp-auth/` | Field/non-field errors; five bad attempts expire flow. |
| [`PGPChallengeForm`](../accounts/forms.py) — `pgp_auth.html` | `signature` textarea; optional; 32,768. `recovery_code` text; optional; 64. `clean()` requires exactly one of signature or recovery code; signature/fingerprint and single-use hash checks server-side. | `POST /accounts/pgp-auth/` | Form error; attempt count; code consumed atomically. |
| [`ProfileForm`](../accounts/forms.py) — `profile.html` | `session_expiry_seconds` select; required; only 1,800, 3,600, or 7,200 seconds. | `POST /accounts/profile/` | Invalid field redisplayed; valid update redirects. |
| [`DepositAddressForm`](../accounts/forms.py) — `deposits.html` | `chain` choice; required; one of the configured `Chain` choices. | `POST /accounts/profile/deposits/new/` | Invalid chain/service failure redisplays the form; successful request redirects with a message. |
| [`WithdrawalForm`](../accounts/forms.py) — `withdrawals.html` | `payout_address` model choice; required; only own active, verified, unlocked addresses. `amount` integer; required; minimum 1 and maximum current available balance. `idempotency_key` hidden text; required; max 128. Service rechecks address state, available balance, caps, provider support, and 3% commission. | `POST /accounts/profile/withdrawals/` | Field/domain errors are redisplayed; success redirects to own status page. |
| [`WalletAddressForm`](../accounts/forms.py) — `wallets.html` | `address` text; required; 64; TRON address normalization/validation in service. | `POST /accounts/profile/wallets/challenge/` | Form or service validation shown; response 400 for invalid input. |
| [`WalletSignatureForm`](../accounts/forms.py) — wallet and payout verify screens | `signature` text; required; 132; strict signature format and recovered TRON address must match. | `POST /accounts/profile/wallets/challenge/<id>/` or `/accounts/profile/payout-addresses/verify/<id>/` | Signature errors shown; challenges expire/consume and cap attempts. |
| [`PayoutAddressForm`](../accounts/forms.py) — `payout_addresses.html` | `chain` select; required; supported chain choices. `label` text; required; 64. `address` text; required; 255. `address_confirmation` text; required; 255; server normalizes both and requires equality/checksum/network validity. | `POST /accounts/profile/payout-addresses/save/` | Form and service errors redisplayed with 400. |
| [`ListingForm`](../catalog/forms.py) — `listing_form.html` | `category` select; required. `title` text; required; 200. `description` textarea; required; **no maximum**. `price` integer; required; model minimum 1 base unit (100,000,000 units = one base). `stock` integer; required; minimum 0. `is_active` checkbox; optional. `image` image file; optional; Django image-field validation; **no app-level size limit**. `shipping_required` checkbox; optional (model default `True`), but `False` is rejected while digital fulfillment is unavailable. `delivery_zone` model choice; optional; no listing-specific choiceset restriction. | `POST /catalog/vendor/listings/new/` or `/catalog/vendor/listings/<id>/edit/` | Form errors redisplayed; service authorization errors are not caught in these views. |
| [`CheckoutForm`](../catalog/forms.py) — `checkout.html` | `quantity` integer; required; minimum 1 and maximum current stock. `shipping_address` text; required for physical listing; max 255. `shipping_phone` text; required for physical listing; max 32. `delivery_zone` model choice; required only when listing is zone-restricted, otherwise all zones are offered. | `POST /catalog/listings/<listing_id>/checkout/` | Form and stock/domain errors are shown on checkout; successful creation redirects to order detail. |
| [`CatalogSearchForm`](../catalog/forms.py) — `category_list.html`, `search_results.html` | `q` text; optional; max 200. `category` model choice; optional; only categories with active approved-vendor listings. `sort` choice; optional; `newest`, `price_asc`, or `price_desc`. | `GET /catalog/search/` | Invalid values produce form errors and no results; ORM filters parameterize the search. |
| [`VendorListingFilterForm`](../catalog/forms.py) — `vendor_dashboard.html` | `q` text; optional; max 200. `status` choice; optional; blank/active/inactive. | `GET /catalog/vendor/` | Invalid values do not apply filters; form errors are rendered with the dashboard. |
| [`ReviewForm`](../orders/forms.py) — inline `detail.html` | `rating` typed choice; required; integer 1–5. `comment` textarea; optional; max 2,000. | `POST /orders/<order_id>/review/` | Field errors and service errors are redisplayed; non-buyer gets 403; duplicate/unfinalized submission is rejected. |
| [`PackOrderForm`](../orders/forms.py) — `detail.html` | `photo` image file; required; JPG/JPEG/PNG/WebP; maximum 10 MiB; image content decoded and metadata stripped before save. | `POST /orders/<id>/pack/` | Form/validation error page with HTTP 400; permission failures 403. |
| [`DispatchOrderForm`](../orders/forms.py) — `detail.html` | `courier_reference` text; required; 160; service trims and requires 1–160 characters. | `POST /orders/<id>/dispatch/` | Form/validation error page; permission failures 403. |
| [`ProofOfDeliveryForm`](../orders/forms.py) — `detail.html` | `token` text; required; 128; compared via SHA-256 digest; expiry and one-use enforced by service. | `POST /orders/<id>/deliver/` | Form/validation error page. This route uses bearer possession rather than login. |
| [`OpenDisputeForm`](../orders/forms.py) — `detail.html` | `reason` textarea; required; **no maximum**. `evidence_kind` select; required; enum. `description` text; optional; 500. `attachment` file; required; PDF/JPG/JPEG/PNG/WebP; 10 MiB. Image content is decoded/re-encoded and metadata stripped. | `POST /orders/<id>/dispute/` | Validation/permission errors shown on action error page. |
| [`DisputeEvidenceForm`](../orders/forms.py) — `detail.html` | `kind` select; required; enum. `description` text; optional; 500. `attachment` file; required; PDF/JPG/JPEG/PNG/WebP; 10 MiB. | `POST /orders/dispute/<id>/evidence/` | Validation/permission errors shown on action error page. |
| [`PublicRulingForm`](../orders/forms.py) — `review_dispute.html` | `amount_band` text; required; 80; `min-max base` with 1–20 digits each and lower ≤ upper. `category` select; required; queryset restricted to order category. `outcome` select; required; release/refund/partial. `released_amount_base_units` integer; optional; minimum 1, and for partial must be less than order total. | `POST /orders/review/<id>/` | Form/service validation redisplayed; successful ruling redirects. |
| [`OrderFilterForm`](../ops/forms.py) — `order_list.html` | `status` choice; optional; blank or an `Order.State` choice. `city` model choice; optional; configured cities. `start_date`, `end_date` date inputs; optional; ISO `YYYY-MM-DD`; start may not follow end. | `GET /ops/orders/` | Server-side validation; invalid filter form displays errors and leaves the queryset unfiltered. |
| Staff transition form (`orders/detail.html`) | `target_state` select; required; only valid safe target `ACCEPTED` is offered when the order is `FUNDED`. `reason` textarea; required; no maximum length in HTML or service. | `POST /ops/orders/<id>/force-transition/` | Staff-only; service revalidates transition/reason and uses the vendor accept workflow; all other overrides are rejected and errors are flashed. |
| Market switch reason form (`ops/admin_dashboard.html`) | `reason` text; required; max 1,000 in HTML; `feature` comes from the route and must be a known switch. It toggles rather than accepting an enabled value. | `POST /ops/market-switch/<feature>/toggle/` | Staff-only; service requires actor and nonblank reason; persisted change log records actor/state/reason. |

Sources: [`accounts/forms.py`](../accounts/forms.py), [`catalog/forms.py`](../catalog/forms.py), [`orders/forms.py`](../orders/forms.py), [`core/services/register_user.py`](../core/services/register_user.py), [`orders/uploads.py`](../orders/uploads.py), [`payments/address_validation.py`](../payments/address_validation.py).

### Button-only POST forms

These are real HTML forms with CSRF tokens but no user-entered fields: vendor application (`/catalog/vendor/`), vendor approval (`/catalog/admin/vendors/<id>/approve/`), listing deletion (`/catalog/vendor/listings/<id>/delete/`), logout, recovery-code regeneration, wallet unlink, payout-address deletion, payout-address verification-start, staff withdrawal approval, mark-all-notifications-read, and fund/cancel/accept/reject/finalization-extension order actions. Staff withdrawal rejection is a hand-written form with required `reason` text up to 500 characters, validated again by the service. Listing moderation is a Django admin form with only `is_active` editable. Sources: [`accounts/templates/accounts/profile.html`](../accounts/templates/accounts/profile.html), [`accounts/templates/accounts/wallets.html`](../accounts/templates/accounts/wallets.html), [`accounts/templates/accounts/payout_addresses.html`](../accounts/templates/accounts/payout_addresses.html), [`ops/templates/ops/withdrawal_approval.html`](../ops/templates/ops/withdrawal_approval.html), [`catalog/templates/catalog/vendor_apply.html`](../catalog/templates/catalog/vendor_apply.html), [`catalog/templates/catalog/vendor_approval_queue.html`](../catalog/templates/catalog/vendor_approval_queue.html), [`catalog/templates/catalog/vendor_dashboard.html`](../catalog/templates/catalog/vendor_dashboard.html), [`orders/templates/orders/detail.html`](../orders/templates/orders/detail.html), [`ops/templates/ops/admin_dashboard.html`](../ops/templates/ops/admin_dashboard.html), [`core/templates/core/notifications.html`](../core/templates/core/notifications.html).

### Django Admin forms

Admin forms are generated by Django, not declared in project `forms.py`. These are also server-side validated; Django admin presents its own field and permission errors.

| Admin form/screen | Fields | Validation / editability |
|---|---|---|
| User add | `username` (required, max 150, unique), `password1`, `password2` (required, Django password validators and match), `is_staff`, `is_active` | Custom `AdminUserCreationForm`; staff permission checks apply. |
| User change | `username`, `session_expiry_seconds` (30/60/120 minutes), `is_active`, `is_staff`, `is_superuser`, `groups`, `user_permissions`, `password`, `last_login`, `date_joined` | Custom `AdminUserChangeForm` plus `UserAdmin` fieldsets; permissions and timestamps follow Django admin/model behavior. |
| Category | `name` (required, max 100, unique), `slug` (required, max 120, unique; prepopulated from name) | Model field validation and uniqueness. |
| City | `name` (required, max 100, unique), `slug` (required, max 120, unique; prepopulated from name) | Model field validation and uniqueness. |
| Delivery zone | `city` (required FK), `name` (required, max 100) | Unique city/name constraint. |
| Vendor profile, listing, dispute, evidence inline, public ruling, order | Listing: only `is_active` editable; vendor profile and other financial/operational records are read-only or change-disabled. | Listing moderation changes visibility immediately; no payment/settlement action is available from the admin model screens. |

Sources: [`accounts/admin.py`](../accounts/admin.py), [`catalog/admin.py`](../catalog/admin.py), [`orders/admin.py`](../orders/admin.py), [`catalog/models.py`](../catalog/models.py), [`orders/models.py`](../orders/models.py). Payments, ledger, and ops models have no registered admin classes. The admin does not provide withdrawal approval.

## 4. Functionality implemented in source

“Implemented” below means the relevant route/service/model logic exists and has tests or explicit error handling; it does **not** mean the production environment or live provider was verified.

| Capability | Evidence and scope |
|---|---|
| PGP-backed account registration/login, hashed recovery codes, logout, session duration | [`accounts/views.py`](../accounts/views.py), [`core/services/pgp_auth.py`](../core/services/pgp_auth.py), [`core/services/authenticate_user.py`](../core/services/authenticate_user.py), [`accounts/tests.py`](../accounts/tests.py). |
| Vendor application, staff approval, listing create/edit/delete, optional listing image upload; active listings filtered by approved vendor | [`catalog/views.py`](../catalog/views.py), [`catalog/forms.py`](../catalog/forms.py), [`catalog/models.py`](../catalog/models.py), [`core/services/approve_vendor.py`](../core/services/approve_vendor.py), [`core/services/save_listing.py`](../core/services/save_listing.py), [`core/services/delete_listing.py`](../core/services/delete_listing.py), [`catalog/tests.py`](../catalog/tests.py). |
| Public category/listing browsing | [`catalog/views.py`](../catalog/views.py), [`catalog/templates/catalog/`](../catalog/templates/catalog). |
| Catalog search and vendor listing filters | [`catalog/forms.py`](../catalog/forms.py), [`catalog/views.py`](../catalog/views.py), [`catalog/test_discovery.py`](../catalog/test_discovery.py). |
| Buyer reviews and listing aggregates | [`core/services/submit_review.py`](../core/services/submit_review.py), [`catalog/models.py`](../catalog/models.py), [`catalog/review_signals.py`](../catalog/review_signals.py), [`catalog/test_reviews.py`](../catalog/test_reviews.py). |
| In-app notifications, unread badge, read actions, and related-resource links | [`core/models.py`](../core/models.py), [`core/services/notify.py`](../core/services/notify.py), [`core/views.py`](../core/views.py), [`core/test_notifications.py`](../core/test_notifications.py), [`accounts/templates/accounts/_site_header.html`](../accounts/templates/accounts/_site_header.html). |
| Append-only balanced ledger postings, account locking, insufficient-funds checks, reconciliation command | [`core/services/post_transfer.py`](../core/services/post_transfer.py), [`ledger/models.py`](../ledger/models.py), [`ledger/management/commands/reconcile.py`](../ledger/management/commands/reconcile.py), [`ledger/tests.py`](../ledger/tests.py). |
| User deposit address/history pages and deposit event/state/conversion/reversal services | [`accounts/views.py`](../accounts/views.py), [`accounts/templates/accounts/deposits.html`](../accounts/templates/accounts/deposits.html), [`core/services/poll_deposits.py`](../core/services/poll_deposits.py), [`core/services/convert_deposit.py`](../core/services/convert_deposit.py), [`core/services/reverse_deposit.py`](../core/services/reverse_deposit.py), [`payments/tests.py`](../payments/tests.py). |
| Payout-address book, chain validation, 24-hour lock, required TRON proof for withdrawal | [`accounts/views.py`](../accounts/views.py), [`core/services/save_payout_address.py`](../core/services/save_payout_address.py), [`core/services/verify_payout_address_challenge.py`](../core/services/verify_payout_address_challenge.py). |
| Internal-ledger order escrow, delivery proof, evidence, and dispute ruling | [`core/services/fund_order.py`](../core/services/fund_order.py), [`core/services/settle_order_escrow.py`](../core/services/settle_order_escrow.py), [`core/services/order_transitions.py`](../core/services/order_transitions.py), [`orders/views.py`](../orders/views.py), [`orders/tests.py`](../orders/tests.py). |
| XMR multisig order escrow integration | [`core/services/monero_order_escrow.py`](../core/services/monero_order_escrow.py), [`payments/monero_escrow_gateway.py`](../payments/monero_escrow_gateway.py), [`payments/models.py`](../payments/models.py), [`payments/views.py`](../payments/views.py), [`docs/MONERO_MULTISIG_ESCROW.md`](./MONERO_MULTISIG_ESCROW.md). Kola coordinates an independent gateway, confirms callbacks, accounts for outstanding escrow liabilities, and credits ledger balances after confirmed settlement; the external 2-of-3 signer gateway itself is not in this repository. |
| Scheduled order deadlines and quote cleanup | [`orders/management/commands/run_scheduler.py`](../orders/management/commands/run_scheduler.py), [`deploy/systemd/kola-scheduler.timer`](../deploy/systemd/kola-scheduler.timer). |
| Aggregate and per-chain reserve reporting, operational kill switches, public canary, dependency health | [`core/services/reserve_report.py`](../core/services/reserve_report.py), [`core/services/reserve_integrity.py`](../core/services/reserve_integrity.py), [`ops/views.py`](../ops/views.py), [`ops/management/commands/`](../ops/management/commands/), [`deploy/systemd/mk-reserve-integrity.timer`](../deploy/systemd/mk-reserve-integrity.timer). |
| Private uploads for pack photos/evidence with random names, limits, and image metadata stripping | [`orders/uploads.py`](../orders/uploads.py), [`orders/views.py`](../orders/views.py), [`orders/tests.py`](../orders/tests.py). PDF malware scanning is not present. |

## 5. Broken, incomplete, or risky functionality

1. **Payout verification is chain-limited:** the withdrawal form and service require a verified address, but the signed ownership challenge is implemented only for TRON. Saved BTC/LTC/XMR addresses cannot be used for withdrawals until a chain-specific verification method exists. [`core/services/create_payout_address_challenge.py`](../core/services/create_payout_address_challenge.py), [`core/services/request_withdrawal.py`](../core/services/request_withdrawal.py), [`accounts/forms.py`](../accounts/forms.py).
2. **No persisted cart exists.** Buyers can search/filter catalog results and check out one listing at a time, but cannot save a multi-listing cart. [`catalog/urls.py`](../catalog/urls.py), [`catalog/views.py`](../catalog/views.py), [`catalog/forms.py`](../catalog/forms.py).
3. **Financial provider execution remains deployment-dependent.** Provider support, credentials, RPC/network configuration, and actual settlement were not validated in this audit. [`payments/providers/`](../payments/providers/), [`mk/settings.py`](../mk/settings.py).
4. **Production fake-provider guard:** startup rejects `fake` chain providers when `DJANGO_DEBUG=False`; debug environments can still use them. The guard prevents accidental production use but does not prove real providers are correctly configured. [`mk/settings.py`](../mk/settings.py).
5. **Financial job delivery is outbox-backed but still depends on Redis and worker liveness:** jobs are durable in PostgreSQL and can be reclaimed after stale claims; operators still need to monitor pending/failed jobs. [`core/services/outbox.py`](../core/services/outbox.py), [`payments/management/commands/run_market_worker.py`](../payments/management/commands/run_market_worker.py).
6. **Notifications are in-app only.** Relevant order, dispute, withdrawal, and vendor transitions create database rows, but there is no email delivery or notification for deposit events; delivery depends on the originating transaction committing successfully. [`core/models.py`](../core/models.py), [`core/services/notify.py`](../core/services/notify.py), [`core/services/order_transitions.py`](../core/services/order_transitions.py).
7. **Digital fulfillment is not implemented:** listing forms/services reject digital listings, public discovery and checkout exclude historical digital listings, and the transition table's legacy `digital_delivery` action is not a file submission/download workflow. [`catalog/forms.py`](../catalog/forms.py), [`catalog/views.py`](../catalog/views.py), [`core/services/save_listing.py`](../core/services/save_listing.py), [`core/services/create_order.py`](../core/services/create_order.py), [`core/services/order_transitions.py`](../core/services/order_transitions.py).
8. **Order detail has defensive vendor guards and order-completeness constraints.** These protect application-created rows; legacy/raw database writes should still be covered by migrations and deployment verification. [`orders/models.py`](../orders/models.py), [`orders/templates/orders/detail.html`](../orders/templates/orders/detail.html).
9. **Login throttling is atomic in Redis.** The exact concurrent threshold test covers ten parallel attempts with a five-attempt limit. Redis outages remain an operational dependency and were not simulated as a production incident. [`core/services/authenticate_user.py`](../core/services/authenticate_user.py), [`accounts/tests.py`](../accounts/tests.py).
10. **TronGrid cursor/watermark behavior is implemented but not database-tested here.** Polling follows the provider cursor, retries failures three times with waits of 1/5/25 seconds, and advances a provider/chain watermark only after records are processed. TronGrid's account-transfer API has no block-number query filter, so older pages are rescanned and results are filtered client-side; verify behavior against a live/staging provider and reorg cases. [`payments/providers/trongrid.py`](../payments/providers/trongrid.py), [`payments/models.py`](../payments/models.py).
11. **Django-admin-generated model lists use the default admin pagination.** Catalog search, category, vendor, review, notification, ruling, dispute, vendor-approval, order-history, deposit-history, withdrawal-history, approval-queue, and reserve-history pages are paginated. [`catalog/views.py`](../catalog/views.py), [`orders/views.py`](../orders/views.py), [`core/views.py`](../core/views.py), [`accounts/views.py`](../accounts/views.py), [`ops/views.py`](../ops/views.py).
12. **No global error boundary or structured API error contract.** Project-owned 404/500 templates are present, but unexpected database/provider/runtime errors still use Django's server-error handling. [`mk/urls.py`](../mk/urls.py), [`mk/templates/404.html`](../mk/templates/404.html), [`mk/templates/500.html`](../mk/templates/500.html).
13. **Deployment artifacts are present, but host behavior remains unverified.** Checked-in application units use `/opt/kola` and user `kola`; the Monero daemon uses `/etc/kola/monero.env`. Backup/restore, systemd deployment, and CI have not been run on a target host/runner. [`deploy/systemd/`](../deploy/systemd/), [`scripts/`](../scripts/), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
14. **No real-provider operation or backup/restore drill was validated.** Provider calls require credentials, trusted TRON derivation callable, network/Tor, wallet RPCs, and operational secrets; database-backed tests were unable to connect to the configured PostgreSQL test port. [`payments/providers/`](../payments/providers/), [`.env.example`](../.env.example).

No application TODO/FIXME markers were found in source directories. That does not imply completeness: explicit missing routes and stubs above are independently verifiable.

## 6. Typical marketplace requirements vs current implementation

| Requirement | Status | Evidence / qualification |
|---|---|---|
| Account registration and login | ✅ Implemented | Password + PGP challenge, rate limiting, recovery codes. |
| Password reset | ❌ Missing | No reset route/email; intentionally excluded in spec. |
| Buyer/vendor/admin roles | ⚠️ Partial | Staff and vendor identity exist; delivery group is presentation identity, not a delivery workflow. |
| Vendor application/approval | ✅ Implemented | Pending profile and staff approval. |
| Listing CRUD and product photos | ⚠️ Partial | Listing create/edit supports an optional image field, but no app-level size limit is configured and production media serving is not established by this repository. |
| Catalog categories and detail | ✅ Implemented | Public pages; category listings are paginated. |
| Search/filter | ✅ Implemented | Public substring search, category filter, whitelisted sort orders, and pagination; vendors can filter own listings by active state/title. |
| Cart | ❌ Missing | No cart model or UI. |
| Checkout / order creation | ✅ Implemented | Authenticated checkout creates physical orders from active listings; digital listings are excluded and funding is a separate step. |
| Stock reservation and decrement | ✅ Implemented | Decrement and order creation are atomic and stock is checked under lock. |
| Order lifecycle / escrow | ⚠️ Partial | Order history and physical lifecycle exist; digital fulfillment remains absent and digital listings are disabled. |
| XMR 2-of-3 multisig escrow | ⚠️ Integration only | Kola-side workflow, HMAC callbacks, outbox jobs, settlement accounting, and reserve reporting exist. Production use is blocked until an independently operated signer gateway implements the documented protocol and passes stagenet/security review. |
| Payment processing | ⚠️ Partial | Ledger and crypto provider boundary exist; user deposit/withdrawal surfaces exist; no card processor by design. |
| Crypto deposits | ✅ Implemented | Address creation, recent deposit/status view, paginated history, watcher/conversion. Live provider integration remains unverified. |
| User withdrawals | ⚠️ Partial | Request, history/status, staff approval/rejection, and 3% commission are implemented; verified-address support is currently TRON-only. |
| Delivery/tracking | ⚠️ Partial | Courier reference and token proof supported; no courier integration. |
| Disputes | ✅ Implemented | Participant evidence, staff rulings, escrow settlement, public rulings. |
| Reviews/ratings | ✅ Implemented | One buyer review per finalized order; 1–5 rating, optional comment, aggregate rating/count, and public paginated reviews. |
| Messaging/in-app notifications | ⚠️ Partial | Recipient-scoped in-app event notifications with unread badge/read actions; no user-to-user inbox/chat, email delivery, or deposit notifications. |
| Admin user management | ✅ Implemented | Django Admin staff user management with PGP gate. |
| Admin listing moderation | ✅ Implemented | Staff can change only `is_active` in Django admin; deactivation removes a listing from public search/detail. |
| Admin order management | ⚠️ Partial | Staff can filter/paginate all orders and view details; only `FUNDED` → `ACCEPTED` is available as an audited safe override. Other state changes must use their normal workflow. |
| Analytics | ✅ Implemented | Aggregated status counts, finalized GMV, orders by city, top vendors/listings by order count, dispute totals/outcomes, and 30-day deposit/withdrawal volumes by chain. |
| File uploads | ⚠️ Partial | Private pack photos/evidence and optional listing images; listing image size is not capped in the app, production media serving is not configured here, PDFs have no malware scan, and digital delivery is absent. |
| Reserve/ledger auditability | ✅ Implemented | Append-only ledger controls, reconciliation, reserve snapshots and integrity runs; operational values still require trusted configuration. |

## 7. Non-functional requirements

### Security

- **Good controls:** Django CSRF middleware is enabled; mutating templates include CSRF tokens. PGP authentication uses temporary isolated GnuPG homes with restrictive permissions, bounded input sizes/timeouts, expected fingerprint checks, hashed single-use recovery codes, and Argon2 password hashing. Onion-only production checks exact v3 onion hosts and requires a high-entropy secret. Sensitive address/phone fields use Fernet; private evidence is downloaded through staff-only view. ORM is used for application queries; scheduler raw SQL is parameterized. Sources: [`mk/settings.py`](../mk/settings.py), [`core/middleware.py`](../core/middleware.py), [`core/services/pgp_auth.py`](../core/services/pgp_auth.py), [`orders/fields.py`](../orders/fields.py), [`orders/views.py`](../orders/views.py), [`orders/management/commands/run_scheduler.py`](../orders/management/commands/run_scheduler.py).
- **XSS/CSRF/SQLi:** default Django template autoescaping and ORM are used; no `csrf_exempt` usage or interpolated SQL was found. No JSON API or CORS configuration exists.
- **Risks:** no general per-IP throttling on account creation or all signed-challenge starts; `SESSION_COOKIE_SECURE=False` is intentional only for Tor onion HTTP and therefore depends on the web listener being private. No HSTS/CSP configuration was found; spec deliberately does not use public TLS. Production fake-provider configuration is rejected when `DJANGO_DEBUG=False`.
- **XMR multisig boundary:** Kola never receives participant signing keys and calls only a deployment-allowlisted HTTPS gateway. The callback endpoint uses timestamped HMAC and monotonic event sequences. This remains safe only if the external gateway independently authorizes each participant and never treats Kola's service credential as spend approval; that gateway has not been implemented or verified here. [`payments/monero_escrow_gateway.py`](../payments/monero_escrow_gateway.py), [`payments/views.py`](../payments/views.py), [`docs/MONERO_MULTISIG_ESCROW.md`](./MONERO_MULTISIG_ESCROW.md).
- **Uploads:** pack photos/evidence have extension, size, and image-content checks, with image metadata stripped; PDFs are not malware-scanned. Listing images use Django's `ImageField` validation but have no app-level size limit. No media route is defined in Django, so production serving for listing image URLs must be configured externally; keep private order uploads inaccessible through that public serving path.
- **No secrets are documented here.** `.env.example` contains placeholders and is the configuration reference.

### Performance and scalability

- No application cache configuration or query/result cache was found. Account balances are aggregated from append-only ledger rows on demand, so query cost grows with ledger history. [`ledger/models.py`](../ledger/models.py), [`core/services/post_transfer.py`](../core/services/post_transfer.py).
- Category listings, search results, vendor-owned listings, vendor-approval, dispute, public-ruling, order/payment history, operations orders, and notifications paginate at 25; reviews paginate at 10 and reserve history at 50.
- Catalog category views use `select_related`; no definite N+1 was established in the inspected core pages. Provider polling is sequential; TronGrid uses 200-item pages with cursor traversal and still rescans historical account pages because its endpoint lacks block filters. [`catalog/views.py`](../catalog/views.py), [`payments/providers/trongrid.py`](../payments/providers/trongrid.py), [`payments/providers/btcpay.py`](../payments/providers/btcpay.py).
- The hand-written stylesheet is about 12 KB in the scan; actual dynamic page payload is not measured. The under-40-KB page target is not enforced by a test.

### Accessibility

- Positive evidence: `lang="en"`, viewport metadata, skip link, named nav, semantic main/headings, explicit labels for custom inputs, `aria-live`-style alerts via `role="alert"`, visible focus outlines, responsive breakpoints, and reduced-motion handling. Sources: [`accounts/templates/accounts/_site_header.html`](../accounts/templates/accounts/_site_header.html), [`orders/templates/orders/detail.html`](../orders/templates/orders/detail.html), [`static/css/site.css`](../static/css/site.css).
- No automated accessibility test or contrast measurement is configured. Color-contrast compliance and keyboard screen-by-screen behavior remain unverified.

### Error handling

- Expected form, permission, and state validation errors are handled in account/order forms; `/health/` returns JSON and status 503 when DB/Redis dependencies fail. Scheduler and deposit-poll timestamps are explicitly marked unavailable because no durable run record exists.
- Project-owned 404/500 templates are configured; 500 output avoids stack traces. There is no structured API error contract. Provider/DB exceptions may surface as generic server errors. Some catalog mutation views do not catch service authorization or missing-object errors and rely on Django's default handling.

### State management

- Server-rendered requests and Django sessions; no browser-side application state or JavaScript. Order/withdrawal transitions use explicit transition maps and database transactions/row locks. Ledger entries are append-only.
- Order creation establishes required fields and reserves stock atomically; the model and database constraint reject incomplete funded/active orders.
- Redis sorted sets are fed by a durable transactional outbox and workers claim outbox records with row locks and `SKIP LOCKED`.

### Testing

- pytest + pytest-django; app-level `tests.py` modules cover account, catalog, orders, ledger, payments, ops, and project settings. Tests include service failure cases, concurrency cases, auth/Pgp, uploads, state transitions, providers with mocks, and environment guards.
- `manage.py check`, test collection (235 tests), Python compilation, shell syntax, and CI YAML parsing pass; the isolated TronGrid retry test passes. Migration drift check reports no changes but warns that it could not verify database migration history.
- Database-backed tests, including the new operations/provider/integration tests, could not set up because PostgreSQL at `127.0.0.1:55439` refused connections; the full suite was not verified. No browser/E2E, performance/load, live-provider, or accessibility test configuration was found; CI is configured but has not run from this workspace.

### Deployment readiness

- Environment-backed PostgreSQL/Redis, onion host guard, secret validation, Gunicorn dependency, worker/watcher/scheduler, web unit, encrypted backup/restore scripts and units, CI workflow, and a journal health monitor are present. [`mk/settings.py`](../mk/settings.py), [`.env.example`](../.env.example), [`deploy/systemd/`](../deploy/systemd/), [`scripts/`](../scripts/), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
- Checked-in web, worker, watcher, scheduler, reserve, backup, restore, and monitor units use `/opt/kola` and `kola`. No host installation was verified. No TLS is intentional for the onion deployment, but secure-cookie false makes network boundary validation critical.
- Logging uses Python/Django loggers and systemd journal outputs; no structured log, APM, metrics or external alert delivery backend is configured. `/health/` reports DB/Redis status, queue depth, DB connection information, and explicitly unavailable scheduler/deposit-poll timestamps; the monitor only logs to the journal.
- Production readiness is **not verified** until real provider settings, Tor, wallet RPC security, web listener isolation, backup restore, and database/Redis operation are validated.

## 8. Architecture, data model, and endpoints

### Stack and layers

- Python 3.12 / Django 5.1.15; server-rendered Django templates; PostgreSQL via `psycopg`; Redis queues; Gunicorn WSGI. Dependencies are exactly pinned in [`requirements.txt`](../requirements.txt).
- Apps: `accounts`, `catalog`, `orders`, `ledger`, `payments`, `ops`; project configuration in `mk/`; business operations in `core/services/`; static CSS in `static/`; tests in app `tests.py` and root `tests/`; operations files in `deploy/systemd/`.
- Request flow: URLconf → view (HTTP/auth/form handling) → `core/services` transaction/state logic → Django ORM/PostgreSQL; providers implement external chain/rate calls; durable financial jobs are published to Redis after commit and dispatched by the worker.
- No REST framework or project JSON API. HTML endpoints, JSON health status, stylesheet, and protected file downloads are the app's HTTP surfaces.

### Application models and relationships

| App / tables | Main relationships and purpose |
|---|---|
| `accounts.User` | Custom username user; permissions/groups via Django auth; owns vendor profiles, ledger accounts, orders, addresses, deposits, rate quotes, wallets, and withdrawals. [`accounts/models.py`](../accounts/models.py) |
| `catalog.VendorProfile`, `Category`, `Listing` | Vendor is one-to-one with user and bond account; listing belongs to vendor and category and includes optional image, shipping requirement, and delivery zone. [`catalog/models.py`](../catalog/models.py) |
| `catalog.Review` | One-to-one with order; rating/comment and timestamps. Listing stores denormalized average rating and review count, updated on review creation/deletion. [`catalog/models.py`](../catalog/models.py), [`catalog/review_signals.py`](../catalog/review_signals.py) |
| `orders.City`, `DeliveryZone`, `Order`, `StaffOrderTransition`, `Dispute`, `DisputeEvidence`, `PublicRuling` | City has zones; orders require buyer, vendor, listing, and total; order has quantity, delivery mode and encrypted shipping values; staff transition log preserves actor/from/to/reason; dispute is one-to-one with order; evidence belongs to dispute/user; ruling is one-to-one with dispute and references category. [`orders/models.py`](../orders/models.py) |
| `ledger.Account`, `LedgerEntry` | Account optionally belongs to owner; entry belongs to account and optionally order; amount is signed integer base units. No stored mutable account balance. [`ledger/models.py`](../ledger/models.py) |
| `payments.DepositAddress`, `WalletLink`, `WalletLinkChallenge`, `PayoutAddress`, `PayoutAddressChallenge`, `ChainPollWatermark` | User-owned chain addresses and short-lived challenges; deposit address has chain/transaction deposits; payout address soft delete and availability lock; provider/chain block watermark advances after a complete poll is recorded. [`payments/models.py`](../payments/models.py) |
| `payments.RateTick`, `RateQuote` | Immutable rate samples; quote references two samples and user/chain/amount band. |
| `payments.Deposit`, `DepositEvent`, `Withdrawal` | Deposit belongs to address and optional quote, has append-style event history; withdrawal belongs to user and stores gross, fee, idempotency, state, provider reference, and rejection reason. |
| `core.FinancialJob` | Durable JSON financial jobs with creation, claim, completion, and error state; Redis enqueue is after-commit. [`core/models.py`](../core/models.py), [`core/services/outbox.py`](../core/services/outbox.py) |
| `core.Notification` | Recipient-scoped in-app event, optional actor, JSON deep-link data, read timestamp, and recipient/read index. [`core/models.py`](../core/models.py) |
| `ops.ReserveIntegrityRun`, `ReserveSnapshot`, `MarketSwitch`, `MarketSwitchChange` | Immutable reserve measurements, persistent global feature switches, and immutable staff switch-change audit events. [`ops/models.py`](../ops/models.py) |
| Django framework tables | `auth_group`, permissions, sessions, content types, admin log, and migrations are provided by installed Django apps; sessions use configured Django session backend. |

Database uses migrations under each app. Explicit constraints include unique user/chain deposit address, unique deposit identity, positive amounts, owner/kind ledger account uniqueness, positive order quantity/total, and active wallet/payout address uniqueness. Foreign keys are predominantly `PROTECT` to preserve financial/audit history. Migration sources: [`accounts/migrations/`](../accounts/migrations/), [`catalog/migrations/`](../catalog/migrations/), [`orders/migrations/`](../orders/migrations/), [`ledger/migrations/`](../ledger/migrations/), [`payments/migrations/`](../payments/migrations/), [`ops/migrations/`](../ops/migrations/).

### External integrations

| Integration | Use / configuration |
|---|---|
| PostgreSQL | Django primary database; `POSTGRES_*` environment values. |
| Redis | login attempt limits and queue sorted sets; `QUEUE_REDIS_URL`, `LOGIN_RATE_LIMIT_REDIS_URL`. |
| Coinbase + Kraken | Public spot rates; requests over configured `socks5h://` Tor proxy. |
| BTCPay Server | BTC/LTC invoice/payment polling and wallet balance; URL/store/API key; no outbound withdrawal support in adapter. |
| TronGrid | TRC-20 transfers, blacklist checks, balance; API URL/key, contract whitelist, symbol/decimals, trusted local address deriver; cursor pagination, retries, and per-provider chain watermark; no outbound withdrawal support. |
| Monero wallet RPC + `monerod` | Separate reserve/hot/payout wallet endpoints; reserve/hot balance/sweep and payout transfer. Local RPC and credentials required in production. |
| GnuPG | Local subprocess for OpenPGP challenge verification; `gpg` executable required. |
| Tor | Local SOCKS transport for rate feeds and node egress. |
| No card gateway, SMTP/email, analytics SaaS, frontend CDN, or external media service | No corresponding implementation/configuration found; card/email absence is explicitly consistent with project intent. |

Evidence: [`mk/settings.py`](../mk/settings.py), [`.env.example`](../.env.example), [`payments/providers/`](../payments/providers/), [`core/services/pgp_auth.py`](../core/services/pgp_auth.py), [`docs/SPEC.md`](./SPEC.md).

### Endpoint inventory

The complete route list is in §1 and route definitions in [`mk/urls.py`](../mk/urls.py), [`accounts/urls.py`](../accounts/urls.py), [`catalog/urls.py`](../catalog/urls.py), [`orders/urls.py`](../orders/urls.py), and [`ops/urls.py`](../ops/urls.py). Payment pages are included under the account URLconf. Project endpoint groups are:

- Public reads: catalog/category/listing, public rulings, reserve history, canary, health.
- Public/auth pre-session: register, login, PGP challenge; bearer-token delivery confirmation.
- Authenticated user: profile, wallets, payout addresses, deposits/history, withdrawals/history/status, checkout, order history, vendor dashboard/listings, order participant actions.
- Staff-only: vendor approval queue/approval, dispute queue/review/evidence download, withdrawal approval/rejection queue, operations dashboard, Django admin.
- Internal CLI/system processes: deposit polling/watching, rate capture/conversion, withdrawal queue/worker, order scheduler, ledger reconciliation, kill switches, reserves, fee and Monero sweeps.

## 9. Recommendations

### Top 10, ranked

1. **P0 — Build and independently review the Monero signer gateway.** The Kola-side XMR multisig integration is not a complete escrow service without an independently operated 2-of-3 signer gateway that implements [`MONERO_MULTISIG_ESCROW.md`](./MONERO_MULTISIG_ESCROW.md), passes stagenet lifecycle tests, and proves Kola credentials cannot authorize participant signatures.
2. **P0 — Complete payout ownership verification for supported networks.** The app requires verified destinations, but the only current verification path is for TRON; implement and test safe proofs for other payout chains before advertising them for withdrawal.
3. **P0 — Validate production provider capability/configuration.** Fake providers are blocked outside debug, but real provider credentials, chain support, RPC security, and settlement behavior must be validated before enabling funds.
4. **P1 — Implement digital delivery before re-enabling digital listings.** Digital listings are currently rejected/hidden, including historical listings, because there is no secure seller handoff and buyer-only download flow.
5. **P1 — Add deposit status notifications.** Notify users when deposits are credited or reversed; current in-app event types cover orders, disputes, withdrawals, and vendor approval only.
6. **P1 — Validate provider polling end-to-end.** Cursor pagination, retries, and per-provider watermarks are implemented; run database-backed backlog/provider-outage tests and validate provider ordering, duplicates, and reorg recovery against staging.
7. **P1 — Validate deployment.** Exercise CI and a controlled encrypted backup/restore drill; validate onion listener isolation and secrets before enabling funds.
8. **P2 — Add operational visibility for outbox/worker failures.** Pending and failed jobs are durable, but they need monitoring and alerting. [`core/models.py`](../core/models.py), [`payments/management/commands/run_market_worker.py`](../payments/management/commands/run_market_worker.py).
9. **P2 — Decide whether multi-item carts are in scope.** Current checkout creates one order per listing; a persisted cart is not present.
10. **P2 — Improve regression and non-functional verification.** Run the new catalog/review/notification tests and full suite when PostgreSQL is available; add missing Monero lifecycle/retry/reserve tests, keyboard/contrast checks, and page payload/query tests.

### Quick wins vs major rework

- **Completed in source:** checkout/atomic stock reservation, order history, deposit/withdrawal UI, staff withdrawal review, audited order operations, listing moderation, analytics, kill-switch controls, 3% commission, custom error pages, pagination, atomic login throttling, fake-provider startup guard, outbox-backed jobs, catalog search/vendor filters, buyer reviews, in-app notifications, cursor-based TronGrid polling, CI, backup/restore artifacts, and health monitoring.
- **Quick wins remaining:** add regression coverage for unsupported payout networks, provider-unavailable UX, and paginated edge cases; expose pending job/worker health metrics. The new Monero database-backed tests still need to run against an available PostgreSQL service.
- **Major rework remaining:** chain-specific address proofs, digital fulfillment, and the external Monero signer gateway. Production paths must be reconciled, and backups/restore, CI, and real-provider operation must be exercised before funds are enabled.

## Resolved product decisions

- Saved BTC/LTC/XMR payout addresses may remain on file but are non-withdrawable until chain-specific ownership proofs exist; withdrawals currently require verified addresses, and only TRON ownership verification is implemented.
- Digital listings remain disabled until a secure digital fulfillment flow is implemented. Historical digital listings are hidden from public discovery and checkout but not deleted.

## Intent vs reality

- The spec describes a multi-vendor marketplace; listing checkout now creates complete orders and atomically reserves stock, while there is no persisted cart.
- Deposit and withdrawal screens now expose user flows. Withdrawal destination verification is currently implemented only for TRON.
- XMR multisig workflows, callback processing, and accounting exist in Kola, but actual multisig signing depends on an external gateway that is not included or validated; this feature is not production-ready.
- Checked-in application units consistently use `/opt/kola` and the `kola` service account. No host installation, backup/restore drill, or CI runner result is available from this workspace.
- Per-chain reserve-integrity monitoring is implemented and scheduled. Production reserve coverage still depends on configured providers and has not been independently verified.
