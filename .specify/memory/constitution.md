<!--
===============================================================================
SYNC IMPACT REPORT
===============================================================================
Version Change: 0.0.0 → 1.0.0 (MAJOR - initial ratification)

Modified Principles: N/A (initial version)

Added Sections:
- Core Principles (5 principles)
  - I. API-First Design
  - II. Dual-Actor Accessibility
  - III. Threat Modeling Integration
  - IV. Audit Trail & Traceability
  - V. Django Integration Patterns
- Security & Authentication
- Development Workflow

Removed Sections: N/A (initial version)

Templates Requiring Updates:
- ✅ plan-template.md - Constitution Check section compatible
- ✅ spec-template.md - User stories align with dual-actor model
- ✅ tasks-template.md - Phase structure compatible

Follow-up TODOs: None
===============================================================================
-->

# Shifter Risk Register Constitution

## Core Principles

### I. API-First Design

Every feature MUST be exposed via a RESTful API before any UI implementation begins.
The API serves as the single source of truth for all operations:

- All CRUD operations on risks, comments, and state changes MUST have corresponding API endpoints
- API endpoints MUST support JSON request/response payloads
- API key authentication MUST be supported for programmatic access
- UI components MUST consume the same API endpoints (no server-side rendering of data)
- API versioning MUST be considered from the start (prefix: `/api/v1/`)

**Rationale**: AI agents perform most of the work. They need first-class API access, not workarounds.

### II. Dual-Actor Accessibility

The system serves two distinct actor types with equal priority:

1. **Human Administrators**: Web UI for visual risk management, browsing, and oversight
2. **AI Agents**: API access for automated risk identification, updates, and resolution

Both actors MUST be able to perform all operations. Design decisions MUST NOT favor one actor
over the other unless explicitly justified:

- Human UI MUST provide intuitive navigation and filtering
- API MUST provide complete programmatic control without requiring UI interaction
- Error messages MUST be structured for both human readability and machine parsing
- Rate limiting and quotas (if any) MUST be documented for AI agent consumption patterns

**Rationale**: The system is explicitly designed for AI-assisted risk management workflows.

### III. Threat Modeling Integration

Every risk entry MUST support structured threat modeling data:

- STRIDE categories (Spoofing, Tampering, Repudiation, Info Disclosure, DoS, Elevation of Privilege)
- Likelihood and impact scoring (standardized scale MUST be defined)
- Attack vector descriptions
- Affected assets/components linkage
- Mitigation status tracking

Risk data models MUST NOT be free-form text only. Structured fields enable automated analysis,
filtering, reporting, and AI agent decision-making.

**Rationale**: A risk register without structured threat data is just a todo list.

### IV. Audit Trail & Traceability

All state changes MUST be recorded with:

- Actor identification (user or API key)
- Timestamp (UTC)
- Previous and new state values
- Optional context/reason

Comments MUST be immutable once created. Edits create new comment entries referencing the original.
Deletions are soft-deletes (marked deleted, not removed from database).

Risk lifecycle states (open → acknowledged → mitigating → resolved → closed) MUST be tracked
with transition timestamps and actor attribution.

**Rationale**: Security governance requires complete audit trails. AI agents need history context.

### V. Django Integration Patterns

Implementation MUST follow existing portal conventions:

- New Django app: `risk_register/` (parallel to `mission_control/`)
- Models in `models.py` following existing patterns (soft-delete, timestamps, related_name conventions)
- URL routing under `/risk-register/` for UI, `/api/v1/risks/` for API
- Use existing authentication (Cognito OIDC for UI, API key model for programmatic access)
- Template inheritance from existing portal base templates
- Static assets follow existing patterns (`static/` directory structure)

MUST NOT introduce new frameworks, ORMs, or architectural patterns without explicit justification.
Prefer Django's built-in capabilities and existing project dependencies.

**Rationale**: Consistency with existing codebase reduces cognitive load and maintenance burden.

## Security & Authentication

Authentication MUST support two mechanisms:

1. **Session-based (UI)**: Cognito OIDC integration via existing mozilla-django-oidc setup
2. **API Key (Programmatic)**: Django model storing hashed API keys with:
   - Key prefix for identification (e.g., `rr_live_abc123...`)
   - Key hash (never store plaintext)
   - Associated user/service identity
   - Creation timestamp and optional expiry
   - Revocation capability

API key MUST be settable/rotatable through Django admin interface.

Authorization MUST define clear permission boundaries:
- All authenticated users can read risks
- Risk creation/modification requires specific permissions
- Admin operations (API key management, bulk operations) require elevated privileges

All API endpoints MUST require authentication. No anonymous access.

## Development Workflow

### Testing

Tests SHOULD be written for:
- API endpoint contracts (request/response validation)
- Model state transitions
- Permission enforcement
- Audit trail generation

Django's TestCase and pytest-django MUST be used (per existing `pyproject.toml`).

### Code Organization

```
portal/
├── risk_register/           # New Django app
│   ├── __init__.py
│   ├── admin.py             # Admin interface for risk management
│   ├── api/                  # API views and serializers
│   │   ├── __init__.py
│   │   ├── views.py
│   │   └── serializers.py
│   ├── apps.py
│   ├── migrations/
│   ├── models.py            # Risk, Comment, AuditLog, APIKey models
│   ├── urls.py              # URL routing (UI + API)
│   └── views.py             # Template views for UI
├── templates/
│   └── risk_register/       # Templates for UI
└── tests/
    └── risk_register/       # Tests for the app
```

### Versioning

Data model changes MUST use Django migrations with descriptive names.
API changes MUST maintain backward compatibility within a major version.
Breaking API changes require version increment (`/api/v2/`).

## Governance

This constitution establishes non-negotiable principles for the Shifter Risk Register.

### Amendment Procedure

1. Propose changes with rationale in a dedicated PR/discussion
2. Changes to Core Principles require documentation of impact analysis
3. Update `LAST_AMENDED_DATE` and increment version per semantic versioning

### Versioning Policy

- **MAJOR**: Principle removal or fundamental redefinition
- **MINOR**: New principle added or existing principle materially expanded
- **PATCH**: Clarifications, typos, non-semantic refinements

### Compliance Review

All PRs MUST verify alignment with these principles.
Deviations MUST be explicitly justified in PR description.
Complexity beyond these principles MUST be documented in code comments.

**Version**: 1.0.0 | **Ratified**: 2025-12-13 | **Last Amended**: 2025-12-13
