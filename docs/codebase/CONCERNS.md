# Codebase Concerns

This is a source/config review, not a production security certification. Risks below describe observable implementation gaps and deployment dependencies.

## Top Risks (Prioritized)

| Severity | Concern | Evidence | Impact | Suggested action |
|---|---|---|---|---|
| High | Pytest collection has a `NameError`: `Deposit` is referenced but undefined in a return annotation | `core/services/watch_chain.py`; `.venv/bin/pytest --collect-only -q` | Full test collection stops before all tests can run | Fix/import/quote the annotation, then rerun collection and suite. |
| High | Monero multisig order escrow depends on an external signer gateway absent from this repository | `docs/MONERO_MULTISIG_ESCROW.md`, `payments/monero_escrow_gateway.py` | The app-side integration alone does not provide independent 2-of-3 signing; production feature must remain disabled until reviewed gateway exists. | Implement/deploy independently, test on stagenet, and security-review. |
| High | Production provider/RPC/Tor and backup/restore behavior are not validated | `payments/providers/`, `docs/OPERATIONS.md`, `docs/BACKUP.md` | Funds and recovery depend on correctly configured external services and host boundary | Perform staged provider tests, host hardening review, and controlled restore drill before production funds. |
| High | Payout-address ownership proof is currently TRON-only | `core/services/create_payout_address_challenge.py`, `docs/SPEC.md` | Other saved BTC/LTC/XMR addresses cannot currently be eligible for withdrawal | Implement and test chain-specific ownership verification or keep those methods unavailable. |
| Medium | PostgreSQL at `127.0.0.1:55439` is unavailable in current environment | command output; `docs/codebase/TESTING.md` | Database-backed suite and migration-history check are not verified | Start isolated PostgreSQL/Redis or rely on CI, then rerun checks. |
| Medium | `SESSION_COOKIE_SECURE=False` is intended for onion HTTP and requires strict private-listener/Tor boundary | `mk/settings.py`, `docs/OPERATIONS.md` | Misrouted/public HTTP could expose session cookies | Verify listener/proxy isolation and deployment network rules. |
| Medium | No CSP/HSTS, PDF malware scanning, or automated accessibility/contrast checks found | `docs/MARKETPLACE_AUDIT.md`, `orders/uploads.py` | Browser hardening, uploaded evidence hygiene, and accessibility remain partially unverified | Assess CSP/HSTS compatibility with onion-only HTTP, scan PDFs, add automated checks. |
| Medium | Durable jobs can accumulate/fail without external alert delivery | `core/models.py`, `payments/management/commands/run_market_worker.py`, `docs/OPERATIONS.md` | Stuck withdrawals/settlements may not be visible promptly | Add queue age/failure metrics and alerting. |

## Technical Debt

| Debt item | Why it exists | Where | Risk if ignored | Suggested fix |
|---|---|---|---|---|
| Digital listing state/actions exist but secure digital fulfillment is disabled/unimplemented | Feature intentionally paused pending fulfillment design | `core/services/order_transitions.py`, `catalog/forms.py`, `docs/SPEC.md` | Legacy transition affordance can confuse future changes; cannot safely sell digital items | Keep listing hidden/rejected; remove/complete legacy path after product decision. |
| No persisted multi-listing cart | Current checkout is listing-by-listing | `catalog/views.py`, `docs/MARKETPLACE_AUDIT.md` | Limits buying workflow if cart is expected | [ASK USER] Confirm whether multi-item cart is in scope. |
| DB-aggregated ledger balances can become more expensive as history grows | Balances are derived from immutable rows | `ledger/models.py`, `core/services/post_transfer.py` | Query cost increases with ledger size | Benchmark; consider safe indexed/materialized read model without changing ledger source of truth. |
| TronGrid account transfer pagination may revisit historical pages | Provider API lacks block-number filter; client filters against persisted watermark | `payments/providers/trongrid.py` | Polling cost may grow with address history | Validate staging behavior and consider provider query alternatives/archive indexing. |
| Ruff and formatting policy is not checked into repository | Scan found no lint/format config; local Ruff invocation reports findings | `.codebase-scan.txt`, `accounts/admin.py`, `accounts/forms.py` | Contributors may have inconsistent local checks | [ASK USER] Decide whether to pin/configure lint/formatter in repo and CI. |

## Security Concerns

| Risk | OWASP category | Evidence | Current mitigation | Gap |
|---|---|---|---|---|
| Onion HTTP uses non-secure session cookies | A02 (Cryptographic Failures) | `mk/settings.py`, `docs/OPERATIONS.md` | Production requires onion hosts; documented private listener | Correctness depends on host/network isolation; verify operationally. |
| External XMR gateway holds callback trust boundary | N/A | `payments/monero_escrow_gateway.py`, `docs/MONERO_MULTISIG_ESCROW.md` | Timestamped HMAC, nonce/event sequencing, host allowlist; Kola has no participant keys | Gateway implementation and independent authorization not present/verified. |
| Uploaded PDF evidence has no malware scan | A08 (Software and Data Integrity) | `orders/uploads.py`, `docs/MARKETPLACE_AUDIT.md` | Extension/size and file authorization controls exist | Add scanning/quarantine policy; keep storage private. |
| No CSP/HSTS policy found | A05 (Security Misconfiguration) | `mk/settings.py`, `docs/MARKETPLACE_AUDIT.md` | Django security middleware and clickjacking protection enabled | Evaluate and configure appropriate headers for intended onion deployment. |

## Performance and Scaling Concerns

| Concern | Evidence | Current symptom | Scaling risk | Suggested improvement |
|---|---|---|---|---|
| Ledger balance aggregation scans entry history | `ledger/models.py`, `core/services/post_transfer.py` | Balance is aggregate `Sum` per account | Cost grows as entries accumulate | Profile and add indexes/optimized read model if needed. |
| TronGrid may rescan older transfer pages | `payments/providers/trongrid.py` | Endpoint lacks block-range filtering, watermark filters results client-side | Poll time/API use can increase with historical activity | Measure and optimize polling/indexing strategy. |
| Search uses substring filters without documented full-text/trigram index | `catalog/views.py`, `docs/MARKETPLACE_AUDIT.md` | `icontains` search | Large catalogs may have slow queries | Add indexes/search backend only when measured and needed. |

## Fragile/High-Churn Areas

| Area | Why fragile | Churn signal | Safe change strategy |
|---|---|---|---|
| Financial services/provider flows | Concurrency, retries, irreversible external sends, ledger invariants | No Git repository/history is available in this workspace; churn unknown | Add focused tests, preserve idempotency, inspect DB state machines and provider capability contracts. |
| `core/services/watch_chain.py` | Current annotation prevents test collection | No Git history available | Correct narrowly; rerun pytest collection. |
| Project history | Scan reported no recent commits; terminal confirms workspace is not a Git repository | Not measurable | [TODO] Review Git history in the source repository to identify true high-churn files. |

## [ASK USER] Questions

1. [ASK USER] Should digital listings be supported, and if so which secure fulfillment model is intended (private file delivery, text/license-key handoff, or another workflow)?
2. [ASK USER] Is a persisted multi-listing cart in scope, or is one-listing-per-checkout intentional?
3. [ASK USER] Should Ruff/formatting be a repository-enforced convention, and if so which checks should CI enforce?

## Evidence

- `docs/codebase/.codebase-scan.txt` — repository inventory, no TODO markers, no lint config, no Git history/churn data.
- `core/services/watch_chain.py`, `payments/test_monero_escrow.py`, `docs/MONERO_MULTISIG_ESCROW.md`
- `core/services/create_payout_address_challenge.py`, `payments/providers/`, `mk/settings.py`
- `docs/OPERATIONS.md`, `docs/BACKUP.md`, `orders/uploads.py`
- `ledger/models.py`, `core/services/post_transfer.py`, `payments/providers/trongrid.py`, `catalog/views.py`
