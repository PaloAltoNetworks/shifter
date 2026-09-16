---
id: PLAT-235
title: "Member invitations and onboarding"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
created_at: 2026-08-01T17:37:05.299523Z
updated_at: 2026-08-01T17:41:19.898031Z
---

# PLAT-235: Member invitations and onboarding

## Statement

The platform shall provide an email invitation flow for adding members who may not yet have an account, using signed, expiring tokens issued and verified server-side, with resend and revoke, plus an SPA surface to issue and track invitations (pending/accepted/expired/revoked) with role assignment. The flow shall reuse the platform's existing email and token infrastructure rather than a bespoke token scheme.

## Rationale

The current add-member path requires an already-existing user, which does not support onboarding new people into a shared deployment. A signed-token email invitation is the standard, proven pattern and should reuse existing email/token infrastructure rather than be hand-rolled.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1942`
