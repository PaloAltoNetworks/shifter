---
id: UX-050
title: "Automated accessibility testing in CI"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:39:06.880538Z
updated_at: 2026-09-07T00:00:00.000000Z
---

# UX-050: Automated accessibility testing in CI

## Statement

Automated accessibility testing (for example axe-core or equivalent) shall run on every pull request against representative pages. New violations introduced by a pull request shall fail the build. Existing violations shall be tracked in a baseline that can only shrink, not grow.

## Rationale

A11y tooling catches a substantial fraction of WCAG failures automatically. Without a CI gate, regressions are inevitable and the baseline drifts. The "baseline can only shrink" pattern lets the project tackle existing debt incrementally without blocking other work.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/e2e/a11y/axe.spec.ts` (@axe-core/playwright scans over the surface/state matrix on every PR)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/e2e/a11y/matrix.ts` (the registered surface/state matrix)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/accessibility_baseline.py` (exact-finding baseline non-growth ratchet)
- IMPLEMENTS → CI `.github/workflows/deploy.yml` (Accessibility PR Gate job, every PR)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1526` (browser accessibility gate implementation)
- TESTS → TEST `scripts/adr_guard/tests/test_accessibility_baseline.py` (baseline non-growth ratchet)
- TESTS → TEST `shifter/shifter_platform/frontend/src/test/a11y-surface-reconcile.test.ts` (fail-closed surface reconciliation)
- DOCUMENTS → ADR `docs/adr/index.yaml` (ADR-055 browser-regression and non-growing-baseline contract)
- DOCUMENTS → DOCUMENTATION `docs/architecture/continuous-accessibility-enforcement-preflight-713.md` (Tool selection, CI cadence, coverage inventory, failure semantics, and baseline algorithm)
- DOCUMENTS → GITHUB_ISSUE `713` (Architecture decision for continuous accessibility enforcement)
