---
id: CTF-1202
title: "API Authentication"
status: DRAFT
type: INTERFACE
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:24.136977Z
updated_at: 2026-03-26T06:09:57.146709Z
---

# CTF-1202: API Authentication

## Statement

CTF API endpoints shall use the platform's API authentication (PLAT-102) for both session-based and token-based access. CTF-specific API tokens should be scoped to specific events and roles (organizer, participant). All CTF API endpoints except the public scoreboard shall require authentication. The CTF layer shall not implement its own authentication middleware.

## Rationale

API authentication is a platform capability. CTF composes with PLAT-102, adding event-scoped token support rather than building a separate auth layer.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#634` (CTF-1202: API Authentication)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/_access.py` (All API views use @login_required (session auth only) - NO token auth system)
