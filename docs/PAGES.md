# Page inventory

This is the page-level delivery map. `Wave` marks pages covered by the current public, auth, catalog, checkout, and balance build. P2P is deferred. Sizes in the current wave are checked against the rendered response body by `tests/test_page_size.py`; the public styleguide limit is 20 KB and the application page limit is 40 KB.

| Area | Page | Route | Wave |
|---|---|---|---|
| Public | Home | `/` | Current |
| Public | How it works | `/how-it-works/` | Current |
| Public | Canary | `/canary/` | Current |
| Public | Public rulings list | `/orders/rulings/` | Current |
| Public | Public ruling detail | `/orders/rulings/<id>/` | Current |
| Public | Proof of reserves | `/reserves/` | Current |
| Auth | Register | `/accounts/register/` | Current |
| Auth | Login | `/accounts/login/` | Current |
| Auth | PGP challenge | `/accounts/pgp-auth/` | Current |
| Auth | PGP enrollment | `/accounts/pgp-auth/` (enrollment mode) | Current |
| Auth | Recovery-code login | `/accounts/recovery-login/` | Current |
| Auth | Recovery-code regeneration | `/accounts/profile/recovery-codes/` then `/accounts/pgp-auth/` | Current |
| Auth | Sign-out confirmation | `/accounts/logout/confirm/` | Current |
| Catalog | Category index | `/catalog/` | Current |
| Catalog | Category listing | `/catalog/categories/<slug>/` | Current |
| Catalog | Search | `/catalog/search/` | Current |
| Catalog | Listing detail | `/catalog/listings/<id>/` | Current |
| Catalog | Vendor public profile | `/catalog/vendors/<username>/` | Current |
| Checkout | Cart | `/catalog/cart/` | Current |
| Checkout | Checkout confirm | `/catalog/checkout/confirm/` | Current |
| Checkout | Order created | `/catalog/order-created/` | Current |
| Orders | Order list | `/orders/` | Planned |
| Orders | Order detail | `/orders/<id>/` | Planned |
| Orders | Dispute form | `/orders/<id>/dispute/` | Planned |
| Orders | Evidence thread | `/orders/dispute/<id>/evidence/` | Planned |
| Orders | Extend finalize | `/orders/<id>/extend-finalize/` | Planned |
| Orders | Review form | `/orders/<id>/review/` | Planned |
| Orders | Vendor reviews | `/catalog/listings/<id>/reviews/` | Planned |
| Balance | Balance overview | `/accounts/profile/balance/` | Current |
| Balance | Per-chain deposit panel | `/accounts/profile/deposits/` | Current |
| Balance | Deposit list | `/accounts/profile/deposits/history/` | Current |
| Balance | Quote and convert | `/accounts/profile/deposits/<id>/quote/` | Current |
| Balance | Withdrawal request | `/accounts/profile/withdrawals/` | Current |
| Balance | Withdrawal history | `/accounts/profile/withdrawals/` | Current |
| Balance | Payout address book | `/accounts/profile/payout-addresses/` | Current |
| Balance | Add payout address | `/accounts/profile/payout-addresses/save/` | Current |
| Balance | Verify payout address | `/accounts/profile/payout-addresses/verify/<id>/` | Current |
| Vendor | Apply | `/catalog/vendor/` (application flow) | Current |
| Vendor | Dashboard | `/catalog/vendor/` | Current |
| Vendor | Add bond | `/catalog/vendor/bond/` (POST action) | Current |
| Vendor | Listing create | `/catalog/vendor/listings/new/` | Current |
| Vendor | Listing edit | `/catalog/vendor/listings/<id>/edit/` | Current |
| Vendor | Delete confirm | `/catalog/vendor/listings/<id>/delete/` | Current |
| Vendor | Order queue | `/catalog/vendor/orders/` | Current |
| Vendor | Payouts | `/catalog/vendor/payouts/` | Current |
| Ops | Dashboard | `/ops/` | Current |
| Ops | Reserve history | `/reserves/` | Current |
| Ops | Dispute queue | `/orders/review/` | Current |
| Ops | Ruling form | `/orders/review/<id>/` | Current |
| Ops | Vendor queue | `/catalog/admin/vendors/` | Current |
| Ops | Maker approval queue | `/catalog/admin/makers/` | Current |
| Ops | Manual withdrawal queue | `/ops/withdrawals/` | Current |
| Ops | Kill switches | `/ops/` | Current |
| Ops | Health | `/ops/health/` | Current |
| Shared | Notifications | `/notifications/` | Planned |
| Shared | Profile | `/accounts/profile/` | Planned |
| Shared | Security | `/accounts/profile/` | Planned |
| Errors | 400 | `/errors/400/` and Django handler | Current |
| Errors | 403 | `/errors/403/` and Django handler | Current |
| Errors | 404 | `/errors/404/` and Django handler | Current |
| Errors | 500 | `/errors/500/` and Django handler | Current |
| Paused | New orders | `/paused/new-orders/` | Current |
| Paused | Withdrawals | `/paused/withdrawals/` | Current |
| Paused | Digital listings | `/paused/digital-listings/` | Current |
| P2P | All P2P pages | No routes | Deferred |
| Queue | Admission waiting | `/queue/` | New |
| Queue | Queue status (JSON) | `/queue/status/` | New |
| Vendor | Signup details | `/vendors/apply/` | New |
| Vendor | Signup details step | `/vendors/apply/details/` | New |
| Vendor | Signup PGP step | `/vendors/apply/pgp/` | New |
| Vendor | Signup payout step | `/vendors/apply/payout/` | New |
| Vendor | Signup review step | `/vendors/apply/review/` | New |
| Vendor | Signup submitted | `/vendors/apply/submitted/` | New |
| Vendor | Listing images step | `/vendor/listings/new/images/` | New |
| Vendor | Listing pricing step | `/vendor/listings/new/pricing/` | New |
| Vendor | Listing details step | `/vendor/listings/new/` | New |
| Vendor | Listing preview step | `/vendor/listings/new/preview/` | New |
| Vendor | Listing submitted | `/vendor/listings/new/submitted/` | New |
| Media | Cleansed image upload (XHR/JSON) | `/media/upload/` | New |
| Early access | Launch gate | `/early/` | New |
| Early access | Invite gate | `/early/invite/<token>/` | New |

Current-wave acceptance also requires a single shared base document, no app template owning `<html>`, `<head>`, or the site header, one H1 per page, a title, real empty states, and no external asset requests. Every new shared component must appear in `/styleguide/`.


## Responsive wireframe coverage

The Mobile · 375px + 320px Penpot page and [mobile_wireframes/contact-sheet.svg](../mobile_wireframes/contact-sheet.svg) cover ten phone views: order list and detail, checkout confirmation, deposit, withdrawal, evidence thread, admin dispute queue, listing detail, collapsed header search, and an order list at the 320px minimum. The frame-to-template and shared-partial implementation map is in [WIREFRAME_IMPLEMENTATION_MAP.md](WIREFRAME_IMPLEMENTATION_MAP.md). The desktop grayscale audit and per-screen sources are also linked there.
