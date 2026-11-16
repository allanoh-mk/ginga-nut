# Project conventions

- Use Python 3.12, Django 5.1, and PostgreSQL. Pin every runtime and test dependency exactly in `requirements.txt`; do not use open-ended version constraints.
- Keep server-rendered HTML only. Every state-changing interaction is a form `POST` followed by a redirect. Do not add client-side JavaScript, frontend frameworks, CDN assets, or CSS frameworks.
- Keep CSS hand-written in one mobile-first stylesheet. Keep the complete page payload under 40 KB.
- Do not use email for identity, password recovery, or notifications. Notifications are in-app.
- Put business logic in `core/services/`. Each service module exposes one public function; views only handle HTTP input/output and delegate.
- Represent state machines with explicit enums and transition tables. Reject transitions absent from the table; do not encode transition rules as scattered `if` chains.
- Store monetary ledger values as signed integer units in the abstract `base` currency, scaled to eight decimal places. Never use floats or rounded `Decimal` arithmetic for ledger amounts. Do not name a coin outside a provider module.
- Keep the ledger double-entry and append-only. Compute balances from entries; never maintain a mutable balance column.
- Add pytest coverage for every service, including failure paths.
- Keep migrations additive. Never edit a migration that has shipped.
- Read configuration from environment variables. Do not commit credentials or secrets.
- Use role-colored, CSS initials badges instead of profile-photo uploads; initials are the username's first uppercase and second lowercase characters.
- Keep shared page chrome and responsive behavior in reusable templates and the single site stylesheet.
