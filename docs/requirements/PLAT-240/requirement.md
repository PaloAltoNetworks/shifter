---
id: PLAT-240
title: "Administrative audit log and activity history"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
created_at: 2026-08-01T17:37:40.529658Z
updated_at: 2026-08-01T17:41:19.898054Z
---

# PLAT-240: Administrative audit log and activity history

## Statement

The platform shall expose an administrator-facing, read-only audit/activity API over the existing shared.audit record and an SPA surface to search and filter significant administrative events (authentication, membership and role changes, invitations, user-lifecycle and policy changes) by actor, entity, time, and event type. The surface shall read the existing immutable audit records rather than introduce a parallel log.

## Rationale

Administrators of a shared deployment need to answer who changed what and when, especially for membership, role, and policy changes. A read surface over the existing immutable shared.audit record satisfies this without a second logging system (PLAT-241).

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1947`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api/audit.py` (Hardened `/api/v1/audit/` read API: typed query serializer, validated actor/entity/time/action filters, deterministic ordering, session-only authorization)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/administer/AuditPage.tsx` (Staff-facing `/administer/audit` activity-history surface with URL-backed filters and escaped detail disclosure)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/api/audit.ts` (Generated-type TanStack Query data layer over the audit read API)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_audit_store.py` (Behavioral filter, authorization, validation, ordering, and read-only coverage over `/api/v1/audit/`)
- TESTS → TEST `shifter/shifter_platform/frontend/src/features/administer/AuditPage.test.tsx` (SPA filter/URL-mapping, denied/invalid/error states, escaped-disclosure, and accessibility coverage)
