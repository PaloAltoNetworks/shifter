---
id: PLAT-236
title: "User lifecycle administration"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
created_at: 2026-08-01T17:37:09.160800Z
updated_at: 2026-08-01T17:41:19.898036Z
---

# PLAT-236: User lifecycle administration

## Statement

The platform administration surface shall let an administrator manage user account lifecycle - activate, deactivate, and suspend accounts, trigger credential/password reset, and reassign ownership of a departing user's resources - extending the existing /administer users surface and its API, with all state transitions recorded to the audit trail.

## Rationale

The existing /administer users surface covers listing and basic active/inactive and organizer-grant actions but not the fuller lifecycle (suspend, reset, ownership transfer) a shared-infrastructure operator needs when people join and leave. Recording transitions to the existing audit trail keeps offboarding accountable.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1943`
