---
id: GEN-001
title: "Documentation Required for Major Features"
status: ACTIVE
type: NON_FUNCTIONAL
priority: MUST
created_at: 2026-03-20T21:18:27.032056Z
updated_at: 2026-05-09T05:11:30.348297Z
---

# GEN-001: Documentation Required for Major Features

## Statement

All major platform features shall have accompanying user documentation and technical documentation.

## Rationale

As the platform grows, undocumented features become a liability for onboarding, support, and maintenance. Documentation should be treated as a deliverable alongside code.

## Traceability

- IMPLEMENTS → DOCUMENTATION `docs/ops/artifact-preparation.md` (Operator guide for private packs, adapters, preparation and lifecycle)
- IMPLEMENTS → DOCUMENTATION `docs/architecture/raes-in-tenant-artifact-preparation-design-1583.md` (Preparation architecture, contracts, authority and verification)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/index.md` (Top-level in-app documentation index)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/features/index.md` (Feature documentation index)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/index.md` (Technical documentation index)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#670` (GEN-001: Documentation Required for Major Features)
- IMPLEMENTS → CONFIG `docs/adr/documentation-coverage.yaml` (Documentation coverage manifest (major feature -> user+technical docs))
- TESTS → TEST `scripts/adr_guard/tests/test_adr_guard.py` (DocumentationCoverageTests (manifest existence/linkage/coverage invariants))
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/features/ctf.md` (CTF feature user documentation)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/features/ctf-organizer-guide.md` (CTF organizer guide)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/shifter_platform/ctf.md` (CTF technical documentation)
- IMPLEMENTS → CODE_FILE `scripts/adr_guard/_guard/checks/documentation.py` (documentation-coverage adr_guard check (ADR-022-R1), check_documentation_coverage)
