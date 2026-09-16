---
id: CTF-1405
title: "Digest-pinned scenario CTF content hydration"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 1
created_at: 2026-07-29T16:28:15.944295Z
updated_at: 2026-07-29T20:35:31.435519Z
---

# CTF-1405: Digest-pinned scenario CTF content hydration

## Statement

The platform shall hydrate a native CTF event from a bounded, digest-pinned scenario content bundle referenced by deployment-owned scenario configuration. Before an event becomes active, Shifter shall retrieve the private artifact through its existing object-storage boundary, verify its exact digest and closed schema, and atomically create the declared challenges, hints, prerequisite relationships, and supported flag validators. Hydration shall be idempotent, audited, fail closed without partial event content, contain no acquisition or entitlement logic, execute no package-supplied code, preserve the package catalog as reference-only, and remain a transitional resolver that can be replaced by the planned plugin architecture without changing the bundle or event service contract.

## Rationale

Private scenario playtests proved native Shifter challenges and signed-receipt scoring, but operators still had to generate, stage, and invoke catalog imports manually. Repeatable event creation is required before the broader plugin architecture is available. A narrow private-artifact resolver closes that operational gap while reusing the unified scenario catalog, object-storage controls, and native CTF services rather than adding scenario-specific behavior.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `1907` (CTF-1405, Digest-pinned scenario CTF content hydration)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_content_hydration.py` (CTF content hydration service tests)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_content_hydration_concurrency.py` (PostgreSQL hydration transaction tests)
- DOCUMENTS → DOCUMENTATION `docs/dev/ctf-scenario-content.md` (Scenario CTF content operations)
- VERIFIES → PROOF `issue-1907-live-gcp-proof` (Live GCP automatic hydration proof)
- IMPLEMENTS → PULL_REQUEST `Brad-Edwards/shifter#1908` (Digest-pinned scenario CTF content hydration)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/content_hydration.py` (Atomic native CTF content hydration service)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/content_resolution.py` (Digest-pinned private content resolver)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_content_bundle.py` (Closed CTF content bundle contract tests)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_content_resolution.py` (Private content resolution and integrity tests)
