KOLA MARKET — PROJECT README
Version 2.0 · Status build-ready spec · Last revised 2026-11-16

1. Project Overview
Kola Market is a server-rendered, dark-theme marketplace where vendors list physical and digital goods and every transaction is held in 2-of-3 escrow until the buyer confirms delivery. It publishes its own solvency (proof of reserves), its own failure record (public rulings on disputes), and its own liveness (canary entries), so a buyer can verify the operator instead of trusting it. Sellers reach it over Tor with PGP challenge-response login and no email dependency; the operator reaches it through a staff console with kill switches on every money path.

Audience. Privacy-literate buyers and small vendors who want escrow and verifiable solvency without a custodial account, a phone number or a KYC file.

Primary use case. A buyer searches a category, compares vendors by rating and sold volume, funds an order from a per-chain deposit address, and releases escrow on arrival. A vendor lists stock, uploads cleansed images, ships, and gets paid on release.

Platform. Web only. Server-rendered HTML, progressive enhancement, no SPA. Tor-first, clearnet mirror second.

Tech stack. Python 3.12 · Django 5.1 · PostgreSQL 16 · Redis 7 · Celery · Jinja-free Django templates with the project FORM_RENDERER pack · vanilla ES2022 modules · static/css/kola.css + admin.css · Pillow + ImageCms for the media pipeline · GPG via python-gnupg · Nginx + Gunicorn · S3-compatible object store.

⚠️ ASSUMPTION: dark-only for v1. A light theme is deferred, not designed.

2. User Roles & Permissions
Role	Description	Sees	Can	Cannot
Guest	Unauthenticated arrival, possibly in the admission queue	/queue/, /early/, /, /how-it-works/, /canary/, /orders/rulings/*, /reserves/, /catalog/*, listing detail, /accounts/register/, /accounts/login/	Browse, search, filter, sort, read rulings and reserves, register, capture a launch notification	Add to cart, see a balance, message a vendor, review, dispute, see any order
Buyer	Authenticated account, no vendor status	Everything a guest sees, plus cart, checkout, own orders, own disputes, own balance, deposits, withdrawals, payout addresses, notifications, security, settings	Buy, fund, confirm receipt, open and argue a dispute, review a completed order, manage own keys, codes and addresses	Create listings, see other buyers' orders, see admin queues, override escrow, see vendor payout totals
Vendor	Buyer plus an approved vendor application	Buyer set, plus /vendor/listings/*, /vendor/orders/, /vendors/apply/* (until approved), own sales and payout ledger	Everything a buyer can, plus create/edit/pause listings, upload images, mark dispatched, respond in disputes, see own payout schedule	Approve own listings, release escrow to self, edit a ruling, see another vendor's cost basis
Staff / Ops	Operator account in the ops group	Staff console /staff/*: dashboard, vendor queue, maker approval, withdrawal queue, dispute queue, ruling form, kill switches, health	Approve/reject vendors and makers, approve/deny withdrawals, arbitrate disputes and publish rulings, flip kill switches, read health, impersonate read-only	Edit ledger entries directly, delete a published ruling, change another staff member's group, edit model schema from the UI
Superuser	Schema and policy owner	All of the above plus Django admin, /staff/queue/, settings	Everything, including group assignment, queue purge, kill-switch defaults, canary authoring	— (only bound by §4 business rules)
Service	Internal non-human caller (Celery, health probe, queue worker)	Internal endpoints only	Write canary entries, sweep expiries, run the media backfill	Render UI
Role switching. The sidebar item set is resolved server-side from group membership. A buyer never renders "Applications". Staff never render "Balance". A vendor sees both buyer and vendor blocks.

3. All Pages & Screens
Conventions for every entry: E empty · L loading · X error · S success.

Public
/ — Home
Purpose: orient an arrival and route them to a category.
Primary: open a category. Secondary: search, read how-it-works, view reserves.
Layout: full-bleed hero at 640px, category tile grid 4-up at ≥1280, 2-up <768, single column <480. No sidebar.
Components: hero (static), search field (default/focus/error/disabled), category tile (default/hover/focus/pressed/disabled), trust strip with three links, footer.
Nav: to every category, search, how-it-works, rulings, reserves, register, login.
Responsive: hero drops to 420px at 768, text to clamp, tiles 4→2→1, trust strip stacks.
States: E — cold-start banner "Listings open at launch" + notify capture. L — tile skeletons ×8. X — inline "Categories unavailable, retry". S — tiles render with counts.

/how-it-works/ — Explainer
Purpose: explain escrow, disputes, reserves in plain language.
Primary: register. Secondary: read rulings, read canary.
Layout: single 68ch column, numbered steps, sticky step nav ≥1024.
Components: step list, accordion (collapsed/expanded), inline CTA pair.
Nav: register, rulings, canary, home.
Responsive: sticky nav hides <1024, column to 100%.
States: E — n/a (static). L — none (server-rendered). X — fallback copy if a step partial fails. S — renders.

/canary/ — Canary log
Purpose: prove the signing key is live and uncompromised.
Primary: verify the newest signature externally. Secondary: copy fingerprint, read history.
Layout: 72ch, newest-first table of dated statements.
Components: mono fingerprint block with copy, statement table (default/verified/stale), verify instructions.
Nav: home, reserves, rulings.
Responsive: table → card rows <768.
States: E — "No canary statements yet". L — row skeletons ×5. X — "Signature fetch failed". S — rows with dates and status chips.

/orders/rulings/ — Public rulings list
Purpose: the operator's dispute record, in public.
Primary: open a ruling. Secondary: filter by outcome.
Layout: 12-col, 8-col table + 4-col outcome filter rail ≥1024, stacked below.
Components: outcome filter (default/selected/disabled), ruling table, outcome chip (upheld/overturned/split), pagination.
Nav: ruling detail, home.
Responsive: filter rail → chip row → select; table → cards.
States: E — "No rulings published yet". L — skeleton rows. X — "Rulings unavailable". S — rows.

/orders/rulings/<id>/ — Ruling detail
Purpose: one dispute, fully reasoned.
Primary: none (read). Secondary: copy case ID, open the related listing if live.
Layout: 68ch, verdict block first, then reasoning, then evidence appendix.
Components: verdict banner, reasoning prose, evidence list, mono case ID with copy.
Nav: back to list, listing.
Responsive: single column at all widths.
States: E — n/a. L — none. X — "Ruling not found" for a bad ID. S — renders.

/reserves/ — Proof of reserves
Purpose: show liabilities against holdings with a merkle root.
Primary: verify the root externally. Secondary: download the snapshot, read methodology.
Layout: 72ch, headline figures, root block, history table.
Components: figure pair (assets/liabilities), mono root with copy, snapshot download, history table.
Nav: canary, rulings, home.
Responsive: figures stack <480.
States: E — "No snapshot published". L — figure skeletons. X — "Snapshot stale, last good shown" warning bar. S — figures and root.

/catalog/ — Category index
Purpose: the full taxonomy.
Primary: open a category. Secondary: search.
Layout: sidebar (retractable) + 4-up tile grid.
Components: sidebar with category disclosures, tile grid, retract toggle.
Nav: every category, search, home.
Responsive: sidebar → drawer <768; grid 4→2→1.
States: E — "No categories published". L — tile skeletons. X — "Taxonomy unavailable". S — tiles with counts.

/catalog/categories/<slug>/ — Category listing
Purpose: browse one category with sort and filter.
Primary: open a listing. Secondary: sort, filter, paginate.
Layout: sidebar + sticky filter bar + 3-up tile grid.
Components: filter bar (§13 of the contract: range inputs, dual slider, chips, clear-all), sort select, listing tile (image, price, rating, sold volume), pagination.
Nav: listing detail, sibling categories, search.
Responsive: 3→2→1; filter bar → drawer <768.
States: E — "Nothing in this category yet" + sibling suggestions. L — 6 tile skeletons. X — "Load failed, retry". S — tiles with facet counts.

/catalog/search/ — Search results
Purpose: results for a query, refineable.
Primary: open a listing. Secondary: sort, filter, clear, new query.
Layout: as category listing, plus query echo and result count.
Components: identical set plus aria-live count and zero-result block.
Nav: listing detail, categories.
Responsive: as above.
States: E — "No match for '<q>'" + active chips + Clear all + 3 suggestions. L — skeletons. X — "Search failed, retry". S — results + count.

/catalog/listings/<id>/ — Listing detail
Purpose: decide, then buy.
Primary: Add to cart / Buy now. Secondary: message vendor, read vendor profile, read reviews, copy listing ID.
Layout: 7-col gallery + 5-col buy box ≥1024; stacked below with buy box sticky at the bottom <768.
Components: gallery with thumbs, price block (mono), rating + sold volume, quantity stepper, buy buttons, escrow explainer, vendor card, review list, shipping block.
Nav: back to category, vendor profile, cart.
Responsive: gallery full-bleed, buy box becomes a fixed bottom bar with safe-area inset.
States: E — n/a. L — gallery and buy-box skeletons. X — "Listing unavailable" + "out of stock" variant. S — full render with stock chip.

/accounts/register/ — Register
Purpose: create an account without email.
Primary: create. Secondary: log in, read the key warning.
Layout: 480px centred card, BEFORE YOU CONTINUE panel above the form.
Components: username, passphrase + strength meter, confirm, PGP key (optional), ToS checkbox, submit.
Nav: login, home.
Responsive: card full-width <480, panel collapses.
States: E — defaults. L — submit spinner. X — per-field errors, taken username, weak passphrase. S — redirect to recovery-code display.

/accounts/login/ — Login
Purpose: passphrase entry.
Primary: log in. Secondary: PGP challenge, recovery code.
Layout: 440px card.
Components: username, passphrase, submit, three alternate links.
States: E — defaults. L — spinner. X — generic "invalid credentials", rate-limit notice with retry time. S — redirect to intended destination.

/accounts/pgp-auth/ — PGP challenge
Purpose: prove key possession.
Primary: submit signed challenge. Secondary: fall back to passphrase.
Layout: 560px card, challenge block in mono.
Components: challenge block with copy, signature textarea, submit, countdown.
States: E — challenge issued. L — verify spinner. X — bad signature with line count, expired challenge. S — redirect.

/accounts/recovery-login/ — Recovery code
Purpose: get in after key and passphrase loss.
Primary: redeem. Secondary: log in normally.
Layout: 440px card.
Components: code input (mono, grouped), submit, remaining-codes note.
States: E — defaults. L — spinner. X — invalid/used code. S — redirect plus forced key rotation banner.

/accounts/logout/confirm/ — Sign-out confirmation
Purpose: confirm before dropping session.
Primary: sign out. Secondary: cancel.
Layout: 400px centred.
Components: two buttons, session-age line.
States: E — defaults. L — spinner. X — "Session already expired". S — redirect home.

Buyer — commerce
/cart/ — Purpose: review before checkout. Primary: checkout. Secondary: change quantity, remove, keep shopping. Layout: 8-col line items + 4-col summary ≥1024, stacked below. Components: line row (image, title, vendor, price, stepper, remove), summary panel, escrow note. Responsive: rows → cards, summary sticks to bottom. States: E — "Cart empty" + category links. L — row skeletons. X — "Price changed since added" with accept/remove. S — totals recalculate live.

/checkout/confirm/ — Purpose: confirm addresses, chain, fees, terms. Primary: fund escrow. Secondary: back to cart. Layout: 7-col form + 5-col order summary. Components: shipping form, chain select, fee breakdown (mono), terms checkbox, submit. Responsive: stacked, summary first. States: E — n/a. L — quote spinner. X — insufficient balance with deposit link, expired quote. S — redirect to order.

/orders/<id>/created/ — Purpose: tell the buyer what happens next. Primary: view order. Secondary: copy order ID. Layout: 560px centred, mono ID. Components: state timeline, ID with copy, next-step copy. States: E — n/a. L — none. X — "Order created but page failed" fallback. S — renders.

/orders/ — Purpose: all own orders. Primary: open one. Secondary: filter by state. Layout: table ≥1024, cards below. Components: state filter chips, order rows (ID mono, listing, total, state chip, date). Responsive: table → cards. States: E — "No orders yet" + Browse. L — skeletons. X — "Load failed". S — rows.

/orders/<id>/ — Purpose: one order, its escrow state, its actions. Primary: confirm receipt or open dispute. Secondary: copy ID, message vendor, view listing. Layout: 8-col detail + 4-col escrow timeline. Components: state timeline, item block, totals, action pair, message thread. Responsive: stacked, actions to a fixed bar. States: E — n/a. L — skeleton. X — "Order not found". S — renders per state.

/orders/<id>/dispute/ — Purpose: open a dispute with evidence. Primary: submit. Secondary: back to order. Layout: 68ch form. Components: reason select, statement, evidence uploader (cleansed pipeline), submit. States: E — defaults. L — upload progress. X — field errors, size/type rejects. S — redirect to thread.

/orders/<id>/dispute/thread/ — Purpose: argue the case to a ruling. Primary: post. Secondary: attach evidence. Layout: 72ch chronological thread + composer pinned bottom. Components: message blocks, evidence thumbs, composer, ruling banner once decided. States: E — "No messages yet". L — skeletons. X — "Post failed, retry" keeping the draft. S — appends.

/orders/<id>/review/ — Purpose: rate a completed order. Primary: submit. Secondary: skip. Layout: 520px card. Components: star input, body textarea, submit. States: E — defaults. L — spinner. X — "Already reviewed". S — thanks + link to listing.

Money
/balance/ — Purpose: funds overview across chains. Primary: deposit. Secondary: withdraw, convert, history. Layout: 12-col — per-chain cards 2-up, ledger table below. Components: balance card (mono), deposit/withdraw buttons, ledger table, pending banner. Responsive: cards 2→1, table → cards. States: E — "No funds yet" + deposit. L — skeletons. X — "Balance unavailable" + last-good. S — figures.

/balance/deposit/<chain>/ — Purpose: fund. Primary: copy address. Secondary: view QR, set amount, back. Layout: 520px, address block centred. Components: mono address with copy, QR, expiry countdown, expected-confirmations note. States: E — address generating. L — spinner. X — "Address pool empty, retry". S — address live.

/balance/deposits/ — Purpose: deposit history. Primary: open one. Secondary: filter chain. Layout: table. Components: chain filter, rows (txid mono truncated to full on expand, amount, confirms, state). States: E — "No deposits". L — skeletons. X — "Load failed". S — rows.

/balance/convert/ — Purpose: quote and convert between chains. Primary: execute quote. Secondary: re-quote. Layout: 480px card. Components: from/to selects, amount, quote block (mono, rate, fee, expiry), confirm. States: E — defaults. L — quoting. X — expired quote, insufficient, pair unavailable. S — conversion row.

/balance/withdraw/ — Purpose: request a withdrawal. Primary: submit. Secondary: pick a saved address. Layout: 480px card. Components: chain, address select or manual, amount, fee line, submit. States: E — defaults. L — spinner. X — below minimum, address invalid, insufficient. S — redirect to history.

/balance/withdrawals/ — Purpose: withdrawal history. Primary: open one. Secondary: filter. Layout: table. Components: rows (ID mono, chain, amount, state). States: E — "No withdrawals". L — skeletons. X — "Load failed". S — rows.

/balance/addresses/ — Purpose: payout address book. Primary: add. Secondary: verify, remove, set default. Layout: table. Components: rows (label, mono address, verified chip, actions). States: E — "No saved addresses" + add. L — skeletons. X — "Load failed". S — rows.

/balance/addresses/add/ — Purpose: add an address. Primary: save. Secondary: back. Layout: 480px card. Components: chain select, address, label, save. States: E — defaults. L — spinner. X — checksum invalid, duplicate. S — redirect to book.

/balance/addresses/<id>/verify/ — Purpose: prove ownership by signature. Primary: submit signature. Secondary: back. Layout: 520px, challenge in mono. Components: challenge block, signature field, submit. States: E — challenge shown. L — verifying. X — bad signature. S — verified chip.

Account
/notifications/ — Purpose: all notices. Primary: open. Secondary: mark all read, filter. Layout: 720px list. Components: unread dot, rows, mark-all, filter tabs. States: E — "Nothing new". L — skeletons. X — "Load failed". S — rows.

/security/ — Purpose: keys, codes, sessions. Primary: rotate key. Secondary: regenerate codes, revoke session. Layout: 720px stacked panels. Components: key block (mono fingerprint), code counter, session table. States: E — n/a. L — none. X — "Rotation failed". S — panels with current state.

/settings/ — Purpose: profile and preferences. Primary: save. Secondary: change passphrase, export data. Layout: 560px sections. Components: display name, timezone, notification toggles, passphrase change, export. States: E — prefilled. L — spinner. X — field errors. S — saved bar.

Vendor
/vendor/listings/ — Purpose: own stock. Primary: new listing. Secondary: edit, pause, preview. Layout: table. Components: rows (thumb, title, price mono, stock, state chip, actions). States: E — "No listings" + create. L — skeletons. X — "Load failed". S — rows.

/vendor/listings/new/images/ — Purpose: upload cleansed images. Primary: continue. Secondary: reorder, set cover, remove, retry. Layout: 4-up grid, 8 slots. Components: drop zone, per-tile progress, cover badge, remove, reject reason. States: E — empty slots. L — per-tile progress. X — type/size reject with reason + retry. S — 8 filled, continue enabled.

/vendor/listings/new/pricing/ — Purpose: price, currency, stock, shipping. Primary: continue. Secondary: back. Layout: 560px form. Components: price (mono), currency, quantity, origin, destinations. States: E — defaults. L — none. X — field errors. S — advances.

/vendor/listings/new/details/ — Purpose: title, category, condition, description. Primary: continue. Secondary: back. Layout: 68ch. Components: title, category select, condition, markdown description with preview tab. States: E — defaults. L — none. X — errors, unsanitised markdown notice. S — advances.

/vendor/listings/new/preview/ — Purpose: see it as a buyer. Primary: submit for review. Secondary: edit any block. Layout: buyer listing detail plus a preview watermark. Components: full listing render, per-block edit links. States: E — n/a. L — none. X — "Missing: image/price" blocking list. S — submitted.

/vendor/listings/new/submitted/ — Purpose: set expectation. Primary: view listing. Secondary: create another. Layout: 480px centred. Components: REVIEW chip, queue position, window copy.

/vendor/orders/ — Purpose: orders to fulfil. Primary: mark dispatched. Secondary: message buyer. Layout: table. Components: rows (ID, item, state, action). States: E — "No sales yet". L — skeletons. X — "Load failed". S — rows.

/vendors/apply/ + /details/ /pgp/ /payout/ /review/ /submitted/ — Purpose: five-step vendor application. Primary: advance. Secondary: back, save draft. Layout: 560px, stepper header. Components: step fields, PGP key with fingerprint echo, per-chain payout, ToS checkbox, review blocks with Edit. States: E — defaults. L — key parse spinner. X — unparseable key, checksum fail, duplicate resumes draft. S — PENDING + window.

Queue & launch
/queue/ — Purpose: hold arrivals under load. Primary: wait (auto). Secondary: read the reason. Layout: 480px centred, position band + ETA. Components: position band, ETA, countdown, poll loop. States: E — n/a. L — "finding your place". X — backend down, admit-all notice. S — admitted, redirect.

/queue/full/ — Purpose: queue at cap. Primary: return later. Secondary: notify me. Layout: 480px. Components: come-back timestamp, capture field.

/early/ — Purpose: pre-launch gate, 24h before public. Primary: notify me. Secondary: enter an invite token. Layout: 560px, countdown hero. Components: countdown, capture, token field, three trust links. States: E — before window: coming-soon. L — submit spinner. X — invalid token, already registered. S — confirmed.

/early/invite/<token>/ — Purpose: token entry. Primary: enter. Secondary: capture instead. States: E — valid token. X — expired/used → /early/expired/. S — admitted.

Staff
/staff/ dashboard · /staff/vendors/ queue · /staff/makers/ approval · /staff/withdrawals/ queue · /staff/disputes/ queue · /staff/rulings/new/ form · /staff/switches/ kill switches · /staff/health/ health · /staff/queue/ admission control

Shared: full sidebar rail, dense tables, mono everywhere for IDs and amounts, per-row actions with confirm modals. Each has E ("Queue clear"), L (skeletons), X ("Load failed, retry"), S (rows with counts). Switches add per-switch confirm modals and an audit strip. Health adds sparklines and a stale-data warning.

Failure
/404/ — 68ch centred, "That page isn't here", search field, three links. /500/ — same plus "retry" and a case reference. Both static, both no sidebar.

4. Functional Requirements
4.1 Accounts
Register with username + passphrase, optional PGP key. Validations: username [a-z0-9_]{3,24} unique; passphrase ≥12 chars, zxcvbn ≥3. Screens: register. Roles: guest. Rule: no email required, ever.
PGP challenge-response login. Server issues a nonce with a 120s TTL, verifies the detached signature, single-use. Screens: pgp-auth. Roles: any with a key.
Recovery codes — 10 single-use codes, hashed at rest, shown once at registration and on regeneration. Screens: recovery-login, security.
Session revocation per device, plus revoke-all. Screens: security.
4.2 Catalog
Category browse with disclosure tree and facet counts. Screens: catalog, category.
Search across title and description, Postgres tsvector, with sort and composable filters (§13 of the contract). Screens: search, category.
Listing detail with gallery, stock, rating, sold volume, vendor card. Screens: listing detail.
4.3 Commerce
Cart — server-side, per user, survives session loss. Screens: cart.
Checkout with quote, fee breakdown, chain selection, 15-minute quote TTL. Screens: checkout.
Escrow 2-of-3 state machine: CREATED → FUNDED → DISPATCHED → CONFIRMED → RELEASED, with DISPUTED → RULED branches and EXPIRED on dispatch timeout. Every transition writes a ledger pair.
Dispute with evidence, thread, and a published ruling on close.
Reviews, one per completed order, editable for 14 days.
4.4 Money
Per-chain deposit addresses from a pre-generated pool, single-use, 24h TTL, swept on confirm.
Double-entry ledger — every movement is a balanced pair, immutable, no direct edits.
Withdrawals with a minimum, fee, staff queue, and a signed-address check when the address is saved.
Conversion with a quoted rate and expiry.
4.5 Vendor
Five-step application, draft-persisted, resumable.
Listing creation in four steps with autosave and preview.
Image pipeline with metadata cleansing (see 4.8).
4.6 Ops
Vendor, maker and withdrawal queues with approve/reject and a required reason.
Dispute arbitration producing a ruling, published to /orders/rulings/.
Kill switches per money path — deposits, withdrawals, checkout, registration — each with a confirm and an audit entry.
Proof-of-reserves snapshot publication.
Canary statement authoring and signing.
4.7 Admission control
Capacity gate with signed admission cookie, FIFO ticketing, bounded queue, staff bypass, admin purge.
4.8 Media
Every upload cleansed before storage: orientation baked, sRGB, capped at 2048px, re-encoded, all EXIF/XMP/IPTC/GPS/device/time stripped, filename randomised, assertions re-run on the saved buffer, originals discarded. SVG through a whitelist sanitiser.
4.9 Early access
Window-gated teaser page, token or capture entry, double opt-in, one send only, noindex until launch.
Workflows
W1 — Purchase. search → filter → listing → add to cart → cart review → checkout quote → fund from a deposit address → FUNDED → vendor dispatches → buyer confirms → escrow releases → review.
W2 — Dispute. buyer opens within the window → evidence both sides → thread → staff arbitrate → ruling published → ledger settles per outcome.
W3 — Vendor onboarding. apply details → PGP key (fingerprint echoed) → payout per chain → review → submit → queue → approve → listing rights granted.
W4 — Listing. images (cleansed) → pricing → details → preview → REVIEW → maker approval → live.
W5 — Overload. request over capacity → /queue/ → ticket → poll → admit → signed cookie → next.
W6 — Launch. capture → confirm → 24h window opens → token or capture admits → launch → /early/ 302s to /.

Edge cases
Duplicate username → inline error, no partial account. Same listing added twice → quantity merges. Price moved while in cart → checkout blocks with accept/remove. Quote expired → re-quote required, order not created. Deposit under-confirmed → pending, no credit until threshold. Withdrawal to an unverified address → allowed above a threshold only with confirmation. Two staff claim one dispute → first claim locks, second sees read-only. Concurrent listing edit → last-write-wins with a version field and a conflict notice. Redis down → queue admits all. Upload of a 200MP file → rejected on the megapixel guard. JS off → search, filters, sort, cart and checkout all still submit as plain forms.

5. Non-Functional Requirements
Performance. LCP <2.5s p75 on a mid-range Android over 4G. TTFB <300ms p95. Search <250ms p95. Queue status <40ms p95. CSS <45KB gzipped, JS <30KB. No CLS from late-loading images — every image is dimensioned.

Security. PGP challenge-response or passphrase, Argon2id, session cookies HttpOnly; Secure; SameSite=Lax, 30-day rolling expiry. CSRF on every mutating form. Strict CSP with a nonce, no inline script. Rate limits: login 5/15min per username, register 3/hour per IP, upload 30/hour, capture 3/hour, search 60/min. All money paths idempotent by request key. Every input server-validated; allowlists for sort, chain, state and role. Ledger append-only with a nightly balance assertion.

Scalability. Single Gunicorn box to ~2k concurrent with the queue engaged. Ledger partitioning by month at 1M rows. Media off-box on S3. Read replicas deferred.

Accessibility. WCAG 2.2 AA. Body ≥4.5:1; --muted on --bg is the floor at 4.6:1. Full keyboard paths, visible focus, aria-live on async counts, labelled icon controls, reduced-motion honoured, 44px targets.

Support matrix. Tor Browser 13+, Firefox 128+, Chromium 126+, Safari 17+, mobile Safari iOS 17+, Chrome Android 126+. No IE, no legacy Edge.

Out of scope v1. Light theme, native apps, multi-currency display, saved searches, wishlists, vendor storefront subdomains, P2P transfers, i18n, web push, image CDN transforms, 2FA TOTP.

Compliance. GDPR-shaped: export and erase endpoints, 30-day soft delete, no third-party analytics, no fonts from a CDN. Not HIPAA, not PCI (no card data).

6. Backend Architecture
Style. Server-rendered Django, function-based views, thin views, logic in services/. JSON only for the queue poll and the upload endpoint.

Endpoints (HTML unless noted):

Method	Path	Description	Shape
GET	/	Home	HTML
GET	/catalog/search/?q&sort&min&max&rating&type&page	Search	HTML
GET	/catalog/categories/<slug>/	Category	HTML
GET	/catalog/listings/<id>/	Listing	HTML
POST	/cart/add/	Add	form → 302
POST	/checkout/quote/	Quote	form → 302
POST	/checkout/confirm/	Create order	form → 302
POST	/orders/<id>/confirm/	Release escrow	form → 302
POST	/orders/<id>/dispute/	Open dispute	multipart
POST	/balance/withdraw/	Request	form → 302
POST	/media/upload/	Cleansed upload	JSON {id,url,w,h} / {error,code}
GET	/queue/status/	Poll	JSON {admitted,position,eta}
POST	/early/notify/	Capture	form → 302
GET	/health/	Probe	JSON {db,redis,queue,switches}
POST	/staff/disputes/<id>/rule/	Publish ruling	form → 302
POST	/staff/switches/<key>/	Toggle	form → 302
Data model (all id bigint PK, created_at/updated_at timestamptz):

Entity	Key fields	Relationships	Indexes
User	username, passphrase_hash, group, is_active, version	1-1 Profile, 1-n PGPKey, Order	uq(username)
Profile	display_name, timezone, tos_at	1-1 User	—
PGPKey	fingerprint, armored, is_primary, revoked_at	n-1 User	uq(fingerprint)
RecoveryCode	code_hash, used_at	n-1 User	idx(user, used_at)
VendorApplication	state, draft_token, details_json, payout_json, reason	n-1 User	idx(state, created_at)
Vendor	tier, rating_avg, sold_count	1-1 User	idx(rating_avg desc)
Category	slug, name, parent_id, sort	self-FK	uq(slug), idx(parent, sort)
Listing	title, slug, price_minor, currency, quantity, condition, state, version	n-1 Vendor, Category	GIN(tsv), idx(category,state,price_minor)
ListingImage	image_clean, width, height, position, is_cover	n-1 Listing	idx(listing, position)
Order	public_id, state, subtotal_minor, fee_minor, chain, version	n-1 Buyer, Vendor	uq(public_id), idx(buyer,state), idx(vendor,state)
OrderItem	title_snapshot, price_minor, qty	n-1 Order, Listing	idx(order)
EscrowTransition	from_state, to_state, actor, reason	n-1 Order	idx(order, created_at)
LedgerAccount	code, chain, kind	1-n LedgerEntry	uq(code, chain)
LedgerEntry	direction, amount_minor, pair_id, ref	n-1 LedgerAccount	idx(pair_id), idx(ref)
Deposit	chain, address, txid, confirms, state	n-1 User	uq(address), idx(user,state)
Withdrawal	chain, address, amount_minor, state, reason	n-1 User	idx(state, created_at)
PayoutAddress	chain, address, label, verified_at	n-1 User	uq(user, chain, address)
Dispute	reason, state, claimed_by_id	n-1 Order, Staff	idx(state, created_at)
DisputeMessage	body, is_staff	n-1 Dispute	idx(dispute, created_at)
Ruling	outcome, reasoning, published_at	1-1 Dispute	idx(published_at desc)
Review	rating, body	n-1 Order, Listing	uq(order)
Notification	kind, body, read_at	n-1 User	idx(user, read_at)
Canary	statement, signature, signed_at	—	idx(signed_at desc)
ReserveSnapshot	assets_minor, liabilities_minor, merkle_root	—	idx(created_at desc)
QueueTicket	token_hash, issued_at, admitted_at	—	idx(admitted_at, issued_at)
EarlyInvite	token_hash, email, used_at	—	uq(token_hash)
KillSwitch	key, enabled, changed_by	—	uq(key)
AuditLog	actor, action, object, diff	—	idx(object, created_at)
Auth. Session cookie, Argon2id, PGP nonce table, per-device session rows.

Integrations. Node RPC for chain watchers, SMTP for the single early-access send, S3 for media, GPG for signing. No card processor.

Database. PostgreSQL for tsvector, NUMERIC money, advisory locks on escrow transitions, and partial indexes on queue state. Money is integer minor units everywhere — never float.

Caching. Redis for sessions, rate counters, queue tickets, quote cache (15 min). select_related on every list view. Cache-Control: public, immutable on hashed static and media.

Jobs. Celery: sweep expired quotes and tickets, confirm deposits, expire dispatch timeouts, publish the nightly reserve snapshot, run the media backfill.

Env. SECRET_KEY, DATABASE_URL, REDIS_URL, S3_*, SMTP_*, NODE_RPC_*, EARLY_ACCESS_OPENS_AT, PUBLIC_LAUNCH_AT, QUEUE_CAP, QUEUE_IDLE_TIMEOUT, MIN_WITHDRAWAL_MINOR, UPLOAD_MAX_BYTES, UPLOAD_MAX_PIXELS.

7. Design System
Palette. Dark-only.

Token	Hex	Use
--bg	#0D0D0D	Page ground
--surface	#141414	Cards, panels
--surface-2	#1A1A1A	Inputs, hover fill, raised
--hairline	#2A2A2A	1px borders, dividers
--text	#F2F2F2	Body and headings
--muted	#8A8A8A	Secondary text, floor 4.6:1
--accent	#D4813F	Money and trust only
--accent-hover	#E89A57	Accent hover
--accent-dim	rgba(212,129,63,.12)	Accent wash, chips
--danger	#D4544C	Destructive, failure
--warning	#C9A227	Pending, stale
--success	#4C9E6A	Confirmed, verified
--info	#5B8DBF	Neutral notice
Accent rules: prices, balances, escrow chips, deposit/withdraw CTAs, reserves, rulings, verification, one primary action per screen, ≤5% pixels, greyscale must survive.

⚠️ ASSUMPTION: light-mode values deferred; #FFFFFF/#111111 inverts sketched only.

Typography. Inter 400/500/600 (UI), JetBrains Mono 400/500 (all numerals, IDs, hashes, fingerprints). Scale clamp(): 11 / 12 / 13 / 14 / 16 / 20 / 24 / 32 / 40. Line heights 1.35 body, 1.15 display. Tracking -0.01em ≥24px, 0 below. Labels never under 11px.

Spacing. 4px base, rem: 0.25 / 0.5 / 0.75 / 1 / 1.5 / 2 / 3 / 4 / 5 / 7.5.

Radius. --radius-xs .25rem chips · --radius-sm .375rem buttons, inputs · --radius-md .5rem tiles, cards · --radius-lg .75rem panels, drawers · --radius-xl 1rem modals · --radius-full 999px avatars, retract toggle. Square corners on feature surfaces are defects; table cells and hairlines stay square.

Elevation. L0 flat on --bg. L1 --surface + hairline. L2 --surface-2 + 0 2px 8px rgba(0,0,0,.5). L3 modals 0 12px 40px rgba(0,0,0,.7). No shadow without a surface change.

Grid. 12 columns, 24px gutter, 1440 max, 24/40/64 section padding by width.

Icons. Lucide, 16/20/24, stroke 1.5, currentColor, 44px hit area.

8. UI/UX per Role
Guest. Journey: land → understand escrow → browse → register at the moment of intent. First screen is the home hero with the trust strip emphasised. Tone: plain, reassuring, no jargon. Patterns: no sidebar, minimal chrome, one CTA per screen, register prompt only after a cart attempt. Alerts: launch window banner, queue notices.

Buyer. Journey: search → compare → buy → confirm. First screen is /orders/ if they have orders, otherwise /catalog/. Emphasis on order state and the next action. Tone: factual, second person, state in the past tense ("Funded 2h ago"). Patterns: sidebar with 7 items, sticky filter bar, escrow timeline always visible on order screens. Alerts: funded, dispatched, dispute window closing, withdrawal confirmed.

Vendor. Journey: apply → list → fulfil → get paid. First screen is /vendor/listings/. Emphasis on unfulfilled orders and stock warnings. Tone: operational, terse, deadline-led. Patterns: same sidebar plus a vendor block, dense tables, bulk actions. Alerts: new order, low stock, dispute opened, payout scheduled.

Staff. Journey: queue → claim → decide. First screen is /staff/ with counts per queue. Emphasis on age of oldest item and SLA breach. Tone: clipped, numbered, no politeness. Patterns: full rail, dense tables, per-row confirm modals, audit strip under every action. Alerts: queue depth threshold, switch flip, stale health, ledger assertion failure.

9. Component Library
Component	Variants	States	Key props	Used on
Button	primary, secondary, ghost, destructive	default, hover, focus, active, disabled, loading	label, size, icon, href, disabled, busy	everywhere
Input	text, mono, numeric, password	default, focus, filled, error, disabled, readonly	name, label, hint, error, prefix	forms
Select	native, disclosure	default, open, selected, disabled	name, options, groups	sort, chain, category
Range slider	single, dual	default, dragging, disabled	min, max, step, values	filters
Chip	filter, state, removable	default, selected, hover, removable	label, onRemove, tone	filters, states
Card	listing, panel, stat	default, hover, skeleton	—	catalog, balance, staff
Listing tile	grid, card-row	default, hover, focus, sold-out, skeleton	image, price, rating, sold	catalog, search
Table	dense, standard	default, row-hover, empty, loading	columns, rows	orders, staff
State chip	escrow, queue, health	per state	state, label	orders, staff
Modal	confirm, form	opening, open, closing	title, body, actions	staff, destructive
Drawer	filter, sidebar, sheet	closed, open, closing	side, trap	filters, nav
Stepper	progress, quantity	—	steps, current	checkout, listing, apply
Disclosure	category, section	collapsed, expanded, disabled	label, panel, level	sidebar
Back link	inline	default, hover, focus	href, label	sub-flows
Copy field	address, hash, id	default, copied, error	value, mono	balance, rulings
Uploader	dropzone, tile	idle, progress, done, rejected	accept, max, onReject	listing images
Toast	info, success, danger	entering, visible, leaving	tone, message	global
Skeleton	line, block, tile	—	w, h	all loading
Empty block	—	—	heading, action	all empty
Countdown	inline, hero	running, expired	target	deposits, early
10. File & Folder Structure
Kola_market/
├── manage.py
├── kola/                       settings, urls, wsgi, celery
├── accounts/                   user, pgp, recovery, sessions
├── catalog/                    category, listing, search, filters
├── cart/                       cart, checkout, quote
├── orders/                     order, escrow, dispute, ruling, review
├── ledger/                     accounts, entries, deposits, withdrawals, convert
├── vendors/                    application, listing creation, fulfilment
├── staff/                      queues, switches, health, rulings, queue control
├── queue_gate/                 admission middleware, tickets, status
├── early/                      window gate, invites, capture
├── media/                      upload endpoint, cleansing pipeline, backfill cmd
├── notifications/
├── services/                   escrow.py ledger.py pricing.py cleansing.py
├── templates/
│   ├── base.html               base_public.html  base_app.html  base_staff.html
│   └── partials/               one file per §9 component
├── static/css/                 kola.css (tokens first) admin.css
├── static/js/                  queue-poll, sidebar, filters, uploader, copy
├── docs/                       PAGES.md WIREFRAME_IMPLEMENTATION_MAP.md
│                               DESIGN_AUDIT.md adr/
├── mobile_wireframes/          contact-sheet.png + sources
├── wireframes/                 desktop SVGs
├── tests/                      pipeline, escrow, filters, queue, a11y
└── CREDITS.md  README.md
11. Acceptance Criteria
Escrow. ☐ every transition writes a balanced ledger pair ☐ illegal transitions 409 ☐ dispatch timeout expires ☐ release requires buyer or ruling ☐ test: double-release idempotent.
Media. ☐ GPS, serial, software, timestamp gone ☐ orientation preserved ☐ ≤2048px ☐ filename random ☐ original discarded ☐ .image.url never in a template ☐ test: fixture with full EXIF asserts empty.
Search. ☐ sort allowlisted ☐ filters compose with sort and pagination ☐ zero-result block ☐ canonical drops params ☐ no-JS submits ☐ test: unknown sort ignored.
Queue. ☐ over-capacity 302s ☐ static and health exempt ☐ staff bypass ☐ cap enforced ☐ Redis down admits all ☐ test: cookie is signed and tamper-proof.
Filters. ☐ chips removable ☐ Clear all at 2+ ☐ facet counts correct ☐ 320px no overflow ☐ test: 15-width matrix.
Early access. ☐ before window → coming-soon ☐ inside window → gate ☐ after launch → 302 ☐ noindex during ☐ capture deduplicated ☐ one send only.
Vendor apply. ☐ draft resumes ☐ key fingerprint echoed ☐ ToS unticked by default ☐ PENDING on submit ☐ test: duplicate resumes.
Listing. ☐ submit blocked without image/price/category/origin ☐ autosave ☐ preview watermarked ☐ REVIEW on submit.
Global. ☐ greps clean ☐ greyscale holds ☐ 320–1440 no horizontal scroll ☐ axe clean ☐ keyboard-complete ☐ zero hex outside tokens.

12. Roadmap
Phase 1 — MVP. Accounts (passphrase + PGP + recovery), catalog, search with sort/filter, listing detail, cart, checkout, escrow state machine, ledger, deposits, withdrawals, orders, disputes, reviews, vendor apply, listing creation, media cleansing, all staff queues, kill switches, health, 404/500. Exit: one full purchase and one full dispute cycle end to end on staging.

Phase 2 — Trust surfaces. Canary, proof of reserves, public rulings, admission queue, early access, notifications, security centre, exports.

Phase 3 — Scale. Ledger partitioning, read replicas, saved searches, P2P transfers, light theme, i18n, TOTP.

Dependencies: 2 needs 1's ledger and order state. 3 needs 2's volume to justify. Early access (2) must precede any public launch, so it ships before Phase 1's launch milestone even though it sits in Phase 2's list.

Open assumptions, flagged for confirmation: dark-only; no card payments; no email at registration; single-region; 24h early window is a settings value, not fixed; radius scale replaces sharp geometry on new work only, existing sharp screens migrate opportunistically rather than in one sweep.


# Kola Market — README

> Derived from the working repository. Where the brief was silent, assumptions are flagged `⚠️ ASSUMPTION`. Everything here is buildable from a clean checkout plus the environment variables in §6.8.

## 1. Project Overview

**Pitch.** Kola Market is a Tor-only, server-rendered marketplace where buyers fund orders from an internal balance, funds sit in market escrow until delivery, and everything settles in Monero. It exists because the darknet treats Africa as a shipping surcharge: three-week post, customs roulette, and no local supply. Kola runs same-day courier in four cities, tracked road lanes on three corridors, and digital delivery everywhere else, with a double-entry ledger, published reserves and public dispute rulings underneath.

**Audience.** Crypto-native buyers in Nigeria, Kenya and South Africa first; diaspora buyers of African goods second; vendors with real local stock and a PGP key third.

**Problem solved.** Convenience and recourse. Same-day delivery with escrow and a 72-hour ruling SLA is the entire product; everything else is plumbing.

**Platform.** Web, Tor-only, mobile-first, **zero JavaScript**. Three v3 onion services.

**Stack.** Python 3.12 · Django 5.1 · PostgreSQL 16 · Redis 7 · Gunicorn · systemd · Tor v3 onion services · Caddy absent by design · no CDN, no webfonts, no icon set. Hand-written CSS, one stylesheet. `monerod` (pruned, local, Tor-routed) · BTCPay Server · TronGrid.

⚠️ ASSUMPTION: Django over Laravel because the chain watchers, scheduler and web app share one language.

## 2. User Roles & Permissions

| Role | Description | Can see | Can do | **Cannot do** |
|---|---|---|---|---|
| **Guest** | Unauthenticated visitor | Home, how-it-works, canary, reserves, public rulings, category and listing browse, vendor profiles, styleguide | Browse, search, read rulings, request a PGP challenge | Fund, order, deposit, withdraw, review, see any address or phone |
| **Buyer** | Registered, PGP-verified account | Everything a guest, plus balance, deposits, withdrawals, cart, orders, disputes, notifications, profile, security | Deposit, convert, withdraw, order, confirm delivery, dispute, review, manage payout addresses | List products, accept orders, rule disputes, see other buyers' data |
| **Vendor** | Approved account with funded bond and a `VendorProfile` | Buyer surface plus vendor console, own order queue, own payouts | Create/edit/delete listings, accept/reject/pack/dispatch, see own earnings and bond | Order from another vendor's listing under the same session without a buyer balance, rule disputes, edit a listing with open orders |
| **Staff** | Operator account, PGP-verified, `is_staff` | All queues, dashboards, reserves history, health, kill switches | Approve vendors, approve over-cap withdrawals, rule disputes, publish rulings, toggle kill switches, read metrics | Edit ledger rows, edit a finalized order, delete a vendor's listing, change a ruling after publish |
| **Maker** (deferred, P3) | P2P fiat advertiser | Deferred surface | Deferred | — |

Permission enforcement: role checks live in the service, not the view. A view without a matching service check is a defect.

## 3. All Pages & Screens

Global layout: 960 px max width, 680 px content column, sticky 48 px header (wordmark left, balance + notifications + sign-out right), 44 px footer with canary and fingerprint links. Every page: `title`, single `h1`, breadcrumb if nested, `aria-live` flash region. Under 480 px the header collapses to wordmark + menu link, tables stack to definition lists, and primary actions dock full-width above the footer.

`Loading` on a no-JS site = a `202` page with `<meta http-equiv="refresh" content="5">` and a plain "Checking…" line. `Error` = 400/403/404/500 pages in §3.7. Every screen below inherits those.

### 3.1 Public

**Home** `/` — What Kola is, three categories, four same-day cities, current reserve ratio. Primary: browse categories. Secondary: how-it-works, canary. Layout: no hero image, 3-line intro, category grid 3-up → 1-up, ratio strip. Components: category card (default/hover/focus), ratio strip (ok/degraded/unmeasurable). States: empty n/a; loading n/a; error = ratio strip falls back to "reserves unmeasurable"; success = ratio with timestamp.

**How it works** `/how-it-works` — Escrow, delivery lanes, fees, finalize timers, dispute SLA. Primary: register. Secondary: canary. Static prose, lane table, fee table.

**Canary** `/canary` — Signed statements, fingerprint, last signed date. Primary: copy fingerprint. Components: monospace statement block, copy block (default/copied), date list. States: empty = "No statement yet"; error = signature-verification instructions.

**Reserves** `/reserves` — Per-chain ratio, last run, unmeasurable flags, cold address. Primary: copy cold address. Components: ratio table (ok/degraded/unmeasurable), copy block. States: empty = "First run pending"; error = "Last run failed, see health".

**Public rulings** `/rulings` `/rulings/<id>` — Published rulings, reason text, no names. Primary: open detail. Components: table → cards, pagination (first/prev/next/last, disabled edges).

**Vendor profile** `/vendors/<slug>` — Rating, completed count, member-since, bond status, listings, reviews. Primary: open listing. States: empty = "No listings yet"; empty reviews per COPY.md.

**Styleguide** `/styleguide/` — Every partial in every state, staff-only in production.

### 3.2 Auth

**Register** `/register` — Username, password, PGP key. Primary: create account. Fields with `autocomplete`, `fieldset`/`legend`. Errors: username taken, weak password, unparsable key.

**Sign in** `/login` — Username + password. Primary: sign in. Error: "Sign-in details are incorrect."

**PGP challenge** `/login/challenge` — Nonce in monospace, 5-minute expiry stated. Primary: paste signature, verify. Error: invalid or expired → new challenge link.

**PGP enrollment** `/account/pgp` — For pre-PGP accounts. Primary: save key. Secondary: skip to recovery login.

**Recovery login** `/login/recovery` — Single-use code. Error: "This recovery code has already been used."

**Recovery regeneration** `/account/recovery` — Requires fresh PGP challenge. Renders 10 codes as printable grid, "shown once".

**Sign out confirm** `/logout` — Primary: sign out. Secondary: cancel.

### 3.3 Catalog and checkout

**Category index** `/c/` — All categories with counts. Cards 3-up → 1-up.
**Category listing** `/c/<slug>` — Filter by kind, city, price; sorted newest. Pagination 50.
**Search** `/search?q=` — Listing results, query echoed. Empty: "No listings match <q>."
**Listing detail** `/l/<id>` — Vendor, price in XMR + fiat, stock, kind, description, delivery zones. Primary: add to cart. Secondary: vendor profile, reviews. Disabled add-to-cart with reason when out of stock or zone mismatch. Digital listings show file count and 2-hour finalize.
**Cart** `/cart` — Lines grouped by vendor, per-vendor subtotal, one total. Primary: checkout. Secondary: remove, change quantity. Empty state per COPY.md.
**Checkout confirm** `/checkout` — Address, phone, zone, lane, escrow explanation, exact finalize timer, balance after. Primary: place order. Insufficient balance renders inline with a deposit link, no redirect.

### 3.4 Orders

**Order list** `/orders` — Filter by state, newest first, 50/page.
**Order detail** `/orders/<id>` — Escrow strip (held amount, deadline), state pill, lines, address block, evidence, thread. Controls rendered **only** from the transition table. Primary: context-dependent (fund, confirm delivery, extend). Secondary: open dispute.
**Dispute form** `/orders/<id>/dispute` — Reason, per-rail evidence requirement named. Primary: open dispute.
**Evidence thread** `/orders/<id>/evidence` — Filename, size, timestamp only; upload form. Primary: submit evidence.
**Extend finalize** `/orders/<id>/extend` — Remaining extensions shown. Primary: extend 24 h.
**Review form** `/orders/<id>/review` — 1–5, optional text. Primary: submit review.

### 3.5 Balance

**Wallet overview** `/wallet` — Available, held, per-chain deposit panels. Primary: request deposit address. Secondary: convert, withdraw.
**Deposit panel** `/wallet/deposit/<chain>` — Address in copy block, depth counter, "Spendable after N confirmations. Current: M." Pending deposits greyed.
**Deposit list** `/wallet/deposits` — State pill, depth, amount, txid (truncated, copyable).
**Quote and convert** `/wallet/convert` — Pair, rate, 10-minute lock stated, spread shown. Primary: lock quote, then convert. Error: "Quote expired."
**Withdrawal request** `/wallet/withdraw` — Amount, address picker, caps remaining, fee, 24-hour lock warning. Primary: request withdrawal.
**Withdrawal history** `/wallet/withdrawals` — State, amount, reference.
**Payout address book** `/wallet/addresses` — List, verified badge (TRON only today), lock countdown. Primary: add address.
**Add address** `/wallet/addresses/new` — Double-entry confirmation (paste twice, must match), checksum validation, label. Primary: save.
**Verify address** `/wallet/addresses/<id>/verify` — Signed-message instructions per chain. Primary: verify.

### 3.6 Vendor console

**Apply** `/vendor/apply` — Terms, bond amount, bond funding. Primary: fund bond and apply.
**Dashboard** `/vendor` — Open orders, earnings, rating, bond status, listing count.
**Listing create/edit** `/vendor/listings/new` `/vendor/listings/<id>/edit` — Per-kind field rules; edit blocked with a reason when open orders exist. Primary: save listing.
**Delete confirm** `/vendor/listings/<id>/delete` — Primary: delete.
**Order queue** `/vendor/orders` — Sorted by deadline ascending, remaining time in row. Actions: accept, reject, pack (photo required, or file for digital), dispatch.
**Payouts** `/vendor/payouts` — Earnings, withdrawal entry point.

### 3.7 Ops (staff)

**Dashboard** `/ops` — Liabilities, ratio, open disputes, queue depths, per-city counts.
**Dispute queue** `/ops/disputes` + ruling form `/ops/disputes/<id>` — Split amount in base units with XMR beside it, mandatory published reason, ruling staff recorded. Primary: submit ruling.
**Vendor approval** `/ops/vendors` — Bond, PGP key, sample pack photo. Approve/reject.
**Manual withdrawal queue** `/ops/withdrawals` — Over-cap rows. Approve/reject.
**Kill switches** `/ops/switches` — Two toggles, each labelled with what it stops and does not. Primary: pause/resume.
**Reserve history** `/ops/reserves` — Snapshots, 50/page.
**Health** `/ops/health` — DB, Redis, queue depth, last watcher tick, provider reachability.

### 3.8 System

**Notifications** `/notifications` — Chronological, unread marker, "mark all read".
**Profile** `/account` — Username, joined, vendor link, payout defaults.
**Security** `/account/security` — Key fingerprint, session list with revoke, recovery regeneration, delete account.
**Errors** `/400` `/403` `/404` `/500` — Heading, one sentence, one link home.
**Paused** — Three inline states: orders paused, withdrawals paused, digital unavailable.

## 4. Functional Requirements

**4.1 Accounts** — Register with username + password + PGP key · password then PGP challenge on every sign-in · 10 hashed single-use recovery codes, regenerable behind a challenge · session 30 min, revocable · key fingerprint shown on security page.
**4.2 Ledger** — Append-only, double-entry, integer minor units, balances aggregated never stored · `reconcile` asserts global zero and persists a freeze on failure · eleven fixed accounts · fee accounts swept to treasury daily.
**4.3 Deposits** — One permanent address per user per chain · states SEEN→CONFIRMING→CONFIRMED→CREDITED, plus REVERSED and ORPHANED · spendable only at CREDITED · depth XMR 10, BTC 3, LTC 4, TRC-20 19, USDC 20 · contract whitelist · Tether blacklist poll cached 15 min, failure holds · unknown contract never promotes.
**4.4 Conversion** — Two rate sources, 1% divergence breaker, 10-minute single-use quote bound to user and amount band, 2% spread to `market_spread`, floors all conversions.
**4.5 Withdrawals** — Caps 2/hour-15/day-60 in base units, over-cap to manual approval, worker re-checks, idempotency key per request, 24-hour new-address lock, flat fee to treasury.
**4.6 Catalog** — Vendor approval, bond, listing CRUD, per-kind fields, stock reserved at checkout, digital files private with random names.
**4.7 Orders** — Cart checkout creates one order per vendor, funded atomically or all rolled back · transition table is the only source of truth · finalize timers 2 h digital, 24 h city, 7 d post, 14 d cross-border, two 24 h extensions · split 95/4/1 with remainder to treasury.
**4.8 Delivery** — Zone must match listing, POD token single-use 6 h, pack photo required before dispatch, loss on controlled lanes is market-borne, reship-once on seizure.
**4.9 Disputes** — Per-rail evidence mandatory, 72-hour SLA, published ruling with reason, auto-ruling job at breach, faked reference = ban and bond slash.
**4.10 Digital** — Signed URL, 3 downloads or 72 hours, whichever first.
**4.11 Ops** — Kill switches, reserve page, health, queues, audit of every staff action.

**Core workflow.** Browse → add to cart → checkout with address and zone → fund from balance → vendor accepts → packs with photo → dispatches → POD → buyer confirms or waits for auto-finalize → funds release to vendor, fee and treasury split. Dispute at any post-dispatch point routes to the staff queue instead.

**Edge cases.** Duplicate fund = one transfer. Fund racing cancel = one winner. Out-of-stock line aborts the whole checkout. Deposit reversed after credit = debit plus `suspense` debt. Quote reuse = rejected. Blacklisted sender = held, not credited. Provider down = `202` refresh page. Permission denied = 403. Concurrent finalize on crossed accounts = owner rows locked in ascending user PK.

## 5. Non-Functional Requirements

Performance: page under 40 KB, TTFB under 800 ms on Tor, ledger balance query under 50 ms p95 with 1 M entries. Security: Argon2, PGP challenge, CSRF on every POST, no `csrf_exempt`, encrypted address and phone, onion host allowlist, 10 attempts/hour/IP. Scalability: single VPS to 100 concurrent, then read replica. Accessibility: WCAG 2.2 AA, 4.5:1 body contrast, 3:1 UI, keyboard complete, visible focus, 44 px targets, no colour-only state. Browsers: Tor Browser desktop and Android, 1280 px and 360 px. **Out of scope v1:** P2P, multisig, fiat rails, email, JavaScript, mobile apps, i18n. Compliance: none formal; KYC-free by design.

## 6. Backend Architecture

### 6.1 Routes

| Method | Path | Purpose | Response |
|---|---|---|---|
| GET | `/` | Home | 200 |
| GET | `/c/` `/c/<slug>` | Browse | 200 |
| GET | `/l/<id>` | Listing | 200 / 404 |
| GET/POST | `/cart` | Cart | 200 |
| GET/POST | `/checkout` | Place order | 302 `/orders/<id>` / 400 |
| GET | `/orders` `/orders/<id>` | Orders | 200 / 403 |
| POST | `/orders/<id>/fund` | Fund | 302 / 400 |
| POST | `/orders/<id>/accept` `reject` `pack` `dispatch` | Vendor actions | 302 / 403 |
| GET/POST | `/orders/<id>/dispute` | Dispute | 302 |
| GET | `/wallet` `/wallet/deposits` | Balance | 200 |
| POST | `/wallet/deposit/<chain>` | New address | 302 |
| POST | `/wallet/quote` `/wallet/convert` | Convert | 302 / 400 |
| POST | `/wallet/withdraw` | Withdraw | 302 / 400 |
| GET/POST | `/wallet/addresses/new` | Add address | 302 / 400 |
| POST | `/ops/disputes/<id>/rule` | Ruling | 302 / 403 |
| POST | `/ops/switches/<name>` | Toggle | 302 |

### 6.2 Data model

| Entity | Key fields | Indexes | Relations |
|---|---|---|---|
| User | username, password_hash, is_staff, pgp_fingerprint | username uq | 1–1 Account, 1–n Session |
| Account | kind (11 enum) | kind | n–1 User |
| LedgerEntry | account, amount int, order, created_at | (account, created_at) | immutable, DB trigger |
| Deposit | address, txid, contract, amount, state, depth, blacklisted | (address,txid,contract) uq | n–1 DepositAddress |
| Quote | pair, rate, spread, min, max, locked_until, consumed_at | (user, locked_until) | 1–1 Deposit |
| Withdrawal | amount, address, state, idempotency_key, reference | idempotency_key uq | n–1 User |
| PayoutAddress | chain, address, label, locked_until, verified | (user, address) uq | n–1 User |
| VendorProfile | bond_account, approved_at, rating_avg | slug uq | 1–1 User |
| Listing | kind, price int, stock, zone, active | (category, active) | n–1 VendorProfile |
| Order | state, lane, escrow_amount, deadline, address_enc | (state, deadline) | n–1 User, Vendor |
| Dispute | reason, ruling, split_amount, ruled_by | state | 1–1 Order |
| ReserveSnapshot | chain, ratio, unmeasurable, ran_at | ran_at | — |
| Ruling | order, reason, published_at | published_at | 1–1 Dispute |
| KillSwitch | name, enabled | name uq | — |
| JobOutbox | kind, payload, queued_at | queued_at | — |

### 6.3 Auth · 6.4 Integrations · 6.5 DB · 6.6 Cache · 6.7 Jobs

Auth: session cookie, HttpOnly, SameSite=Lax, Secure off (onion), 30-minute expiry, PGP challenge after password. Integrations: monerod RPC, BTCPay, TronGrid, Coinbase and Kraken rates over `socks5h`, external multisig signer. DB: PostgreSQL, integer money, `select_for_update` in ascending PK order. Cache: Redis for throttling and job queue only, never balances. Jobs: durable outbox, queued post-commit, idempotent handlers, dead-letter after 5 attempts.

### 6.8 Environment

`DJANGO_SECRET_KEY` · `DJANGO_ONION_HOSTS` (3, comma) · `FIELD_ENCRYPTION_KEY` · `POSTGRES_*` · `REDIS_URL` · `CHAIN_PROVIDERS` (fail if `fake` in prod) · `MONERO_RPC_URL` (localhost) · `MONERO_RESERVE_WALLET` `MONERO_HOT_WALLET` `MONERO_PAYOUT_WALLET` · `BTCPAY_URL` `BTCPAY_TOKEN` · `TRONGRID_URL` `TRONGRID_API_KEY` `TETHER_TRC20_CONTRACT` · `WITHDRAWAL_FEE_BASE_UNITS` (required) · `CAPS_PER_TX|HOUR|DAY`.

## 7. Design System

| Token | Light | Dark (reserved) | Usage |
|---|---|---|---|
| Primary | `#12100e` | `#f7f4ef` | Body text, wordmark |
| Accent | `#a4551f` | `#c9743a` | Primary CTA, active nav **only** |
| Background | `#f7f4ef` | `#12100e` | Page |
| Surface | `#efe9e0` | `#1c1917` | Cards, table headers |
| Text secondary | `#5a544c` | `#b3aca2` | Hints, timestamps |
| Border | `#d8cfc1` | `#33302b` | Inputs, dividers |
| Success | `#2f6b3a` | `#4d9e5c` | Credited, delivered |
| Warning | `#8a6412` | `#c9962a` | Pending, locked |
| Error | `#8f2b1e` | `#c0503c` | 4xx, insufficient |
| Info | `#2c4a6b` | `#5f86ad` | Explainer blocks |

Type: system stack `-apple-system, "Segoe UI", Roboto, sans-serif`; mono `ui-monospace, Menlo, monospace`. Scale 13/15/18/24/32; weights 400/600; line-height 1.5 body, 1.2 headings; letter-spacing 0 body, `0.02em` for 13 px caps labels. Spacing 4/8/12/16/24/32/48. Radius 2 px inputs, 3 px buttons, 4 px cards, 0 modals (none). Shadow: one — `0 1px 2px rgb(0 0 0 / .12)` on sticky header only. Grid 12 col, 16 px gutter, 960 px max, 24 px section padding. Icons: none; unicode `→ ← · ✓` only, 1 em.

## 8. UI/UX per Role

**Guest** — Home → category → listing → register. Minimal, guided, ratio strip as credibility. No tables. Notifications none.
**Buyer** — Wallet → deposit → quote → browse → cart → checkout → order → confirm. Balance always in header, escrow strip always on the order. Dense tables on desktop, stacked cards mobile. Alerts: depth confirmations, deadline countdown, dispute opened.
**Vendor** — Queue is the landing page, sorted by urgency. Accept/pack/dispatch as inline row actions. Alerts: new order, deadline 6 h out, dispute opened, bond low.
**Staff** — Sidebar-free, top nav to queues; dense tables, base units beside XMR, everything sortable. Alerts: imbalance freeze, ratio below 1.3, SLA breach, watcher stale.

## 9. Component Library

| Component | Variants | States | Notes | Used on |
|---|---|---|---|---|
| Button | primary, secondary, danger, ghost | default, hover, focus, active, disabled, busy | 44 px min, `aria-disabled` when busy | All |
| Field | text, password, mono, textarea, file, select | default, focus, filled, error, disabled | label + hint + error, `aria-describedby` | All forms |
| Status pill | 12 order states, 6 deposit states | static | colour + text, never colour alone | Order, deposit |
| Table | default, stacked | default, hover row, empty | `<th scope>` | All lists |
| Empty state | default, action | static | COPY.md string + link | All lists |
| Balance strip | default, low | static | available + held | Header, checkout |
| Copy block | address, fingerprint | default, copied | monospace, select-all | Wallet, canary |
| Ratio strip | ok, degraded, unmeasurable | static | — | Home, reserves |
| Pagination | — | default, disabled edges | first/prev/next/last | All lists |
| Countdown | inline, block | static | plain text, no JS | Order, trade |

## 10. File & Folder Structure

```
mk/            settings, urls, middleware (onion host guard)
accounts/      auth, PGP, recovery, sessions
catalog/       vendors, categories, listings, files
orders/        cart, orders, disputes, reviews, uploads, transitions
ledger/        accounts, entries, reconcile, immutability trigger
payments/      addresses, deposits, quotes, withdrawals, providers/
ops/           queues, rulings, switches, reserves, health
core/services/ one function per file, no logic in views
core/jobs.py   outbox, scheduler
static/css/site.css
templates/     base, partials/, one dir per app
deploy/systemd mk-web, mk-worker, mk-watcher, mk-scheduler, timers
docs/          SPEC, PAGES, COPY, AUDIT, DEPLOY, TESTING
```

## 11. Acceptance Criteria

| Feature | Done when | Happy test | Edge test |
|---|---|---|---|
| Fund order | One transfer, order FUNDED | funds, escrow debited | two concurrent → one pair |
| Finalize | 95/4/1 split, remainder to treasury | timer fires, split posted | partial ruling pays fee on released only |
| Deposit | credits only at depth | 19 conf → CREDITED | RBF at 1 conf → SEEN, no entry |
| Reversal | debit + suspense debt | depth drop after credit | balance insufficient → suspense |
| Quote | single-use, banded | convert at locked rate | reuse rejected |
| Withdrawal | caps + idempotency | under cap sends once | crash after broadcast → same key |
| Reserve integrity | freeze above 1% | drift trips switch | missing adapter → unmeasurable |
| Kill switch | blocks path, logs | paused refuses | resume restores |
| Digital | 3 downloads or 72 h | download served | 4th refused |

## 12. Roadmap

**P1 MVP** — physical only, four cities, XMR, ledger, escrow, disputes, ops, deployment. **P2** — digital and fraud categories, cart, reserves page. **P3** — P2P with maker bonds and mobile-money rails. **P4** — multisig escrow via external signer, second signer. P2 depends on the file-serving flow; P3 on P2P views; P4 on the signer gateway being deployed and drilled.