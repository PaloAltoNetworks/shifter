---
id: PLAT-2002
title: "Backend bundles are the OSS backend selection unit"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-05-10T02:49:54.934657Z
updated_at: 2026-05-10T17:32:19.516246Z
---

# PLAT-2002: Backend bundles are the OSS backend selection unit

## Statement

OSS users MUST choose a complete backend bundle rather than composing low-level provider capabilities in the default setup path.

## Rationale

The OSS setup model should be easy to explain and operate: users select AWS, GCP, local, or another backend, while internal capability composition remains an implementation detail.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#722` (Draft requirements and ADR for root-configured backend bundles)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#728` (Migrate AWS support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#729` (Migrate GCP support into a backend bundle)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#731` (Define initial local backend scope)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#725` (Define backend bundle contract and registry)
- DOCUMENTS → DOCUMENTATION `docs/architecture/root-configured-backend-bundles.md` (Root-Configured Backend Bundles)
- CONSTRAINS → ADR `ADR-011` (OSS deployments use root-configured backend bundles)
- IMPLEMENTS → CODE_FILE `shifter/installation/registry.py` (installation.registry, BACKEND_BUNDLES is the single OSS unit of backend selection; derived KNOWN_BACKENDS/KNOWN_PROFILES/ALLOWED_PROFILES)
- IMPLEMENTS → CODE_FILE `shifter/installation/schema.py` (`installation.schema.RootConfig`, derives backend/profile validation from the registry; public selector is `backend: <name>` with no capability-composition keys (extra=forbid))
- TESTS → TEST `shifter/installation/tests/test_registry.py` (tests for installation.registry, registry-is-single-source-of-truth, backend selection unit invariants)
- TESTS → TEST `shifter/installation/tests/test_schema.py` (tests for installation.schema, backend/profile validation derived from the registry; backend settings opaque to the root schema)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#721` (Architecture: root-configured backend bundles for OSS Shifter)
