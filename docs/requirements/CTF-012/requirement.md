---
id: CTF-012
title: "API & Integration"
status: ACTIVE
type: INTERFACE
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.306541Z
updated_at: 2026-03-26T06:34:18.550993Z
---

# CTF-012: API & Integration

## Statement

CTF operations should be exposed as REST API endpoints within the existing Shifter platform API, using the platform's authentication (PLAT-102) and following existing API conventions. The API enables automation, external integrations, and custom tooling built on top of the platform.

## Rationale

An API enables custom scoreboards, automated challenge deployment, integration with chat platforms for solve announcements, and programmatic event management. For Shifter, the API also enables future integration with PANW internal tools. CTF API endpoints are part of the platform API, not a separate service.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (CTF URL configuration - API route definitions)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#626` (CTF-012: API & Integration)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/__init__.py` (CTF Views - API endpoints for CTF operations)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/serializers/communication.py` (Bounded read-only DRF projections for the participant inbox and organizer campaign summary (ADR-051, #2048))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2048` (API contract for scoped communications: bounded serializers and the CTFError -> shared.api.errors mapping)
