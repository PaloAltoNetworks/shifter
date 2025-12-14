# Implementation Plan: Risk Register

**Branch**: `001-risk-register` | **Date**: 2025-12-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-risk-register/spec.md`

## Summary

Build a risk register Django app within the existing Shifter portal that enables both human
administrators and AI agents to manage security risks with full threat modeling support.
The implementation follows API-first design: all features exposed via REST API with API key
authentication for AI agents, session-based auth for humans. Includes complete audit trail
for all state changes.

## Technical Context

**Language/Version**: Python 3.12 (per existing `pyproject.toml`)
**Primary Dependencies**: Django 6.0, Django REST Framework (to add), existing mozilla-django-oidc
**Storage**: PostgreSQL (existing RDS instance)
**Testing**: pytest + pytest-django (existing setup)
**Target Platform**: Linux server (AWS EC2 via Docker)
**Project Type**: Web application (Django monolith with REST API)
**Performance Goals**: <2s page load for 100 risks, <50ms API key auth overhead
**Constraints**: Must integrate with existing Cognito OIDC, follow portal conventions
**Scale/Scope**: Internal tool, <100 concurrent users, <10,000 risks

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. API-First Design | ✅ PASS | All CRUD via `/api/v1/risks/` before UI; API contracts in `contracts/` |
| II. Dual-Actor Accessibility | ✅ PASS | UI views for humans, API endpoints for AI agents; same operations available |
| III. Threat Modeling Integration | ✅ PASS | Risk model includes STRIDE, likelihood, impact, attack vector, affected assets |
| IV. Audit Trail & Traceability | ✅ PASS | AuditLog model captures all state changes with actor attribution |
| V. Django Integration Patterns | ✅ PASS | New `risk_register/` app parallel to `mission_control/`; follows existing patterns |

## Project Structure

### Documentation (this feature)

```text
specs/001-risk-register/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (OpenAPI spec)
│   └── openapi.yaml
└── checklists/
    └── requirements.md  # Specification validation
```

### Source Code (repository root)

```text
portal/
├── risk_register/                # New Django app
│   ├── __init__.py
│   ├── admin.py                  # Django admin for risk management
│   ├── apps.py
│   ├── models.py                 # Risk, Comment, APIKey, AuditLog
│   ├── urls.py                   # URL routing (UI + API)
│   ├── views.py                  # Template views for UI
│   ├── api/
│   │   ├── __init__.py
│   │   ├── authentication.py     # API key auth backend
│   │   ├── permissions.py        # Permission classes
│   │   ├── serializers.py        # DRF serializers
│   │   ├── views.py              # DRF viewsets
│   │   └── urls.py               # API URL routing
│   └── migrations/
├── templates/
│   └── risk_register/            # UI templates
│       ├── risk_list.html
│       ├── risk_detail.html
│       ├── risk_form.html
│       └── apikey_list.html
├── tests/
│   └── risk_register/            # Tests
│       ├── __init__.py
│       ├── test_models.py
│       ├── test_api.py
│       └── test_views.py
└── config/
    └── settings.py               # Add risk_register to INSTALLED_APPS
```

**Structure Decision**: Single Django monolith following existing portal patterns. New
`risk_register` app added parallel to `mission_control`. API endpoints under `/api/v1/`
prefix. UI routes under `/risk-register/`.

## Complexity Tracking

No constitution violations. Implementation uses standard Django patterns with minimal additions.

| Addition | Justification |
|----------|---------------|
| Django REST Framework | Required for API-first design; standard Django API library |
| API Key model | Required for AI agent authentication per constitution |
