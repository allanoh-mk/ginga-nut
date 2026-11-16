# Design audit

Audit date: 2026-11-12. This records implemented template coverage and the viewport checks actually completed in the local browser.

## Acceptance checks

| Check | Result |
|---|---|
| Django system check | Pass: `manage.py check` reports no issues. |
| Template loading | Pass: all 100 project HTML templates load through Django’s template loader. |
| 320px document overflow | Pass on `/accounts/login/` and `/how-it-works/`; no document width exceeded the viewport. |
| Portrait viewport set | Checked on `/accounts/login/`: 320, 360, 390, 414, 480, 640, 768, 820, 1024, 1180, 1280, 1440, 1920, 2560, 3440. |
| Landscape viewport set | Checked on `/how-it-works/`: the same widths, using landscape heights up to 900px; 320px also checked at 320×240. No document overflow observed. |
| 200% zoom at 1280 / 150% at 1024 | Not verified. Browser zoom shortcuts were unavailable in this browser session; equivalent CSS viewport sizes were not counted as browser zoom. |
| OS text scaling +30% | Not verified; no OS text scaling control was available in the browser session. |
| Keyboard register flow | Register screen renders with one H1 and keyboard focus can reach password fields, submit button, and links. No account was submitted. |
| Routes requiring database data | Not fully rendered: local PostgreSQL at 127.0.0.1:55439 was unavailable. Data-backed page checks remain pending. |
| Class attribute source scan | Found 1135 opening HTML elements without an explicit `class` attribute across 100 templates. These include semantic/framework markup; this source audit remains outstanding. |
| Color literals | Pass: palette hex values live in `static/css/kola.css`; no hex literals found in other app CSS/templates. |
| CSS dimensions | No fixed pixel widths on page containers/cards/rails. Pixel widths found are for icons, touch controls, table scroll affordances, and visually hidden text. |
| Viewport units | Layout heights use `dvh`; no `vh` declarations found. Landscape media query uses the `height` feature. |
| Grid/flex minimum sizing | Global `*, *::before, *::after { min-width: 0; }` covers grid and flex descendants. |

## Template inventory

Each template receives the shared Kola tokens and global component styles through the base document or its Django admin stylesheet. Route-specific live rendering is marked separately from shared CSS coverage. “Not independently rendered” means the template is a partial/component or its route needs database-backed state.

| Template | Coverage status | Widths checked |
|---|---|---|
| `accounts/templates/accounts/_site_header.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `accounts/templates/accounts/balance.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/deposit_history.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/deposit_quote.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/deposits.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/login.html` | Live route rendered; one H1; no horizontal overflow. | Portrait: 320, 360, 390, 414, 480, 640, 768, 820, 1024, 1180, 1280, 1440, 1920, 2560, 3440; landscape: shared shell checked on `/how-it-works/`. |
| `accounts/templates/accounts/logout_confirm.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/payout_address_verify.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/payout_addresses.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/pgp_auth.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/pgp_recovery_codes.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/profile.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/recovery_login.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/register.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/wallet_challenge.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/wallets.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/withdrawal_detail.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `accounts/templates/accounts/withdrawals.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/_listing_card.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `catalog/templates/catalog/cart.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/category_detail.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/category_list.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/checkout.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/checkout_confirm.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/listing_delete.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/listing_detail.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/listing_form.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/listing_reviews.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/maker_approval_queue.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/order_created.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/search_results.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/vendor_apply.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/vendor_approval_queue.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/vendor_dashboard.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/vendor_order_queue.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/vendor_payouts.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `catalog/templates/catalog/vendor_public_profile.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `core/templates/core/notifications.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/400.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/403.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/404.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/500.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/admin/app_index.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/base.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/base_site.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/change_form.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/change_list.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/index.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/login.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/admin/widgets/clearable_file_input.html` | Admin theme override; template loads; admin route not rendered. | Not independently checked. |
| `mk/templates/base.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/components/badge.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/balance_strip.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/button.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/copy_block.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/empty_state.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/form_field.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/pagination.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/status_pill.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/components/table.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/forms/field.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/forms/fieldset.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/forms/form.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/forms/formset.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/pagination.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/badge.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/breadcrumb.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/button.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/card.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/empty-state.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/footer.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/header.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/input.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/modal.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/pagination.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/select.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/sidebar.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/stat-tile.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/status-pill.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/table.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/partials/toast.html` | Shared component/partial; inherits redesigned styles. | Through representative parent routes only. |
| `mk/templates/paused/digital_listings.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/paused/new_orders.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/paused/withdrawals.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/public/home.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `mk/templates/public/how_it_works.html` | Live route rendered; one H1; no horizontal overflow. | Landscape: 320, 360, 390, 414, 480, 640, 768, 820, 1024, 1180, 1280, 1440, 1920, 2560, 3440, plus 320×240. Portrait widths checked on `/accounts/login/`. |
| `mk/templates/styleguide.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `ops/templates/ops/admin_dashboard.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `ops/templates/ops/canary.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `ops/templates/ops/health.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `ops/templates/ops/order_list.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `ops/templates/ops/reserve_history.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `ops/templates/ops/withdrawal_approval.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/action_error.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/detail.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/dispute_queue.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/history.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/public_ruling_detail.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/public_rulings.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |
| `orders/templates/orders/review_dispute.html` | Shared redesign styles applied; route not independently rendered. | Pending live route state. |

## Notes

- Width tests covered representative public and auth screens; they do not establish that every data-backed route renders correctly.
- The PostgreSQL service was unavailable during this audit, so route rendering, checkout flow, dynamic tables, and admin pages that query models need a rerun with the development services available.
- The source class scan is reported as an outstanding result rather than being presented as a pass.
