---
id: UX-010
title: "WCAG 2.2 Level AA conformance"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-05-09T04:37:45.763376Z
updated_at: 2026-09-07T00:00:00.000000Z
---

# UX-010: WCAG 2.2 Level AA conformance

## Statement

Every public surface of the platform shall conform to WCAG 2.2 Level AA. Conformance shall be verified by automated tooling on every pull request and by a manual audit before any release that introduces a new surface or significantly changes an existing one. Failures shall block release until remediated or explicitly waived with documented rationale.

## Rationale

No accessibility pass has ever been done on this codebase. WCAG 2.2 AA is the standard baseline for accessible web applications, and treating it as table stakes for an OSS project that wants any kind of public adoption is the floor, anything less excludes users with disabilities and creates legal exposure for adopters.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/e2e/a11y/axe.spec.ts` (per-PR automated WCAG 2.2 A/AA verification of registered surfaces)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/accessibility_baseline.py` (exact-finding baseline ratchet with exact-fingerprint waivers)
- IMPLEMENTS → CI `.github/workflows/deploy.yml` (Accessibility PR Gate job)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1526` (browser accessibility PR-tier gate)
- TESTS → TEST `shifter/shifter_platform/frontend/src/test/a11y-surface-reconcile.test.ts` (fail-closed surface reconciliation)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2117` (remaining ADR-055 tail: nightly matrix, deployed scans, WCAG-EM manual audit, and the release-evidence gate)
- DOCUMENTS → ADR `docs/adr/index.yaml` (ADR-055 continuous accessibility enforcement contract)
- DOCUMENTS → DOCUMENTATION `docs/architecture/continuous-accessibility-enforcement-preflight-713.md` (WCAG scope, manual-audit cadence, release evidence, triage, and waiver design)
- DOCUMENTS → GITHUB_ISSUE `713` (Architecture decision for continuous accessibility enforcement)
