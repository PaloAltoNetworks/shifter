---
id: PLAT-234
title: "Workspace membership and roles administration surface"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
created_at: 2026-08-01T17:37:00.312992Z
updated_at: 2026-08-01T17:41:19.898027Z
---

# PLAT-234: Workspace membership and roles administration surface

## Statement

The SPA shall provide a workspace membership administration surface over the existing membership API (roster, add member, change role, remove member, leave) that renders the closed owner/admin/member role vocabulary and surfaces the last-owner invariant in the UI. The SPA shall consume the server-side role-to-operation policy rather than re-deriving permissions from role codes.

## Rationale

The membership and role API and its fail-closed role-to-operation policy already exist server-side; only the SPA surface is missing. Consuming the server policy rather than re-implementing it in the client keeps a single source of authority (PLAT-241).

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `1941`
