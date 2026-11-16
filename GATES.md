# Gates: Kola Market implementation

OWNS: core/services/watch_chain.py, requirements-dev.txt, pyproject.toml, .pre-commit-config.yaml, catalog/**, orders/**, accounts/**, payments/**, ops/**, core/**, ledger/**, docs/DEPLOY.md, DEPLOY.md, deploy/**, scripts/**, tests/**, GATES.md

Scope: repair test collection and lint baseline, implement buyer/vendor commerce surfaces and digital/cart flows, harden account/payment operations, and complete deployment readiness. Full requested scope inventory is captured in the task request; gates below define the first verifiable increments.

- [ ] G1: pytest collection completes
  CHECK: .venv/bin/pytest --collect-only -q
  EXPECT: collected
  EVIDENCE: pending

- [ ] G2: Ruff lint and formatting checks pass
  CHECK: .venv/bin/ruff check . && .venv/bin/ruff format --check .
  EXPECT: All checks passed!
  EVIDENCE: pending

- [ ] G3: full test suite passes
  CHECK: .venv/bin/pytest -q
  EXPECT: passed
  EVIDENCE: pending

- [ ] G4: requested digital listing flow has coverage and passes
  CHECK: .venv/bin/pytest -q catalog/tests.py orders/tests.py
  EXPECT: passed
  EVIDENCE: pending

- [ ] G5: requested cart checkout is atomic and passes tests
  CHECK: .venv/bin/pytest -q catalog/tests.py
  EXPECT: passed
  EVIDENCE: pending

- [ ] G6: deployment docs and validation artifacts exist
  CHECK: .venv/bin/python -c "from pathlib import Path; p=Path('docs/DEPLOY.md'); assert p.exists() and p.stat().st_size > 0; print('deployment documentation present')"
  EXPECT: deployment documentation present
  EVIDENCE: pending
