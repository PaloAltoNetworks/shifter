---
id: CTF-1201
title: "REST API"
status: DRAFT
type: INTERFACE
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:24.103929Z
updated_at: 2026-03-26T06:34:41.334709Z
---

# CTF-1201: REST API

## Statement

CTF operations should be exposed as REST API endpoints within the Shifter platform API, covering: event CRUD, challenge CRUD, participant management, flag submission, scoreboard retrieval, and hint operations. The API shall follow RESTful conventions with JSON request/response bodies, use the platform's authentication (PLAT-102), and be documented with OpenAPI/Swagger specifications. The API shall support pagination for list endpoints.

## Rationale

A REST API enables programmatic access for custom tooling, automation scripts, external scoreboards, and future mobile clients. For Shifter, the API enables integration with PANW internal tools and custom dashboards. CTF API endpoints are part of the Shifter platform API, not a separate service.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (CTF URL patterns - API route definitions)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#633` (CTF-1201: REST API)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/__init__.py` (CTF Views - API endpoint implementations)
