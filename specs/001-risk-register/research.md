# Research: Risk Register

**Feature**: 001-risk-register
**Date**: 2025-12-13

## Research Topics

### 1. Django REST Framework Integration

**Decision**: Add `djangorestframework` as dependency for API implementation.

**Rationale**:
- Industry standard for Django REST APIs
- Provides serializers, viewsets, authentication backends, and permissions out of the box
- Mature library with extensive documentation
- Already used in similar Django projects

**Alternatives Considered**:
- Django Ninja: Faster, but less mature ecosystem and team familiarity
- Raw Django views with JSON responses: More work, less maintainable
- FastAPI separate service: Violates Django Integration Patterns principle

**Version**: `djangorestframework>=3.15.0`

---

### 2. API Key Authentication Pattern

**Decision**: Implement custom API key authentication using DRF's `BaseAuthentication`.

**Rationale**:
- DRF provides authentication hook points
- Custom implementation allows control over key format, hashing, and storage
- Can integrate with existing Django user model for audit attribution

**Implementation Pattern**:
```python
# API Key format: rr_live_<32-char-random>
# Storage: SHA-256 hash of full key
# Lookup: Key prefix (first 8 chars) for identification
```

**Alternatives Considered**:
- Django REST Framework API Key package: Adds external dependency for simple use case
- JWT tokens: Overcomplicated for service-to-service auth
- OAuth2: Too complex for AI agent use case

---

### 3. Soft Delete Pattern

**Decision**: Follow existing portal pattern with `deleted_at` timestamp field.

**Rationale**:
- Consistent with existing `AgentConfig` model in `mission_control`
- Simple to implement and query
- Supports "view deleted items" admin feature

**Implementation Pattern**:
```python
deleted_at = models.DateTimeField(null=True, blank=True)

@property
def is_deleted(self):
    return self.deleted_at is not None

@classmethod
def active(cls):
    return cls.objects.filter(deleted_at__isnull=True)
```

---

### 4. Audit Log Storage

**Decision**: Store audit entries in dedicated `AuditLog` model with JSON fields for state data.

**Rationale**:
- Follows existing `ActivityLog` pattern in `mission_control`
- JSON fields allow flexible storage of before/after state
- Single table for all entity types simplifies querying

**Implementation Pattern**:
```python
class AuditLog(models.Model):
    entity_type = models.CharField(max_length=50)  # 'risk', 'comment', 'apikey'
    entity_id = models.PositiveIntegerField()
    action = models.CharField(max_length=20)  # 'create', 'update', 'delete', 'close'
    actor_type = models.CharField(max_length=10)  # 'user', 'apikey'
    actor_id = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)
    previous_state = models.JSONField(null=True)
    new_state = models.JSONField(null=True)
    context = models.TextField(blank=True)  # Optional reason/notes
```

---

### 5. STRIDE Categories

**Decision**: Use CharField with choices for STRIDE category, allowing multiple selections.

**Rationale**:
- STRIDE is a fixed set of 6 categories
- Risks can span multiple categories (e.g., both Spoofing and Elevation of Privilege)
- ArrayField (PostgreSQL) allows multiple selections without join table

**Implementation Pattern**:
```python
from django.contrib.postgres.fields import ArrayField

class StrideCategory(models.TextChoices):
    SPOOFING = 'S', 'Spoofing'
    TAMPERING = 'T', 'Tampering'
    REPUDIATION = 'R', 'Repudiation'
    INFO_DISCLOSURE = 'I', 'Information Disclosure'
    DENIAL_OF_SERVICE = 'D', 'Denial of Service'
    ELEVATION = 'E', 'Elevation of Privilege'

stride_categories = ArrayField(
    models.CharField(max_length=1, choices=StrideCategory.choices),
    default=list,
    blank=True
)
```

---

### 6. UI Template Inheritance

**Decision**: Create base template for risk register extending portal base, then extend for each view.

**Rationale**:
- Follows Django template inheritance patterns
- Consistent styling with existing mission_control pages
- Allows risk-register-specific navigation/sidebar

**Implementation Pattern**:
```
templates/
├── base.html                    # Existing portal base
└── risk_register/
    ├── base.html                # Extends base.html, adds RR nav
    ├── risk_list.html           # Extends risk_register/base.html
    ├── risk_detail.html
    └── risk_form.html
```

---

### 7. Pagination Strategy

**Decision**: Use DRF's `PageNumberPagination` for API, Django's `Paginator` for UI.

**Rationale**:
- Standard patterns for each context
- Configurable page size (default 50)
- Supports query parameter customization

**API Response Format**:
```json
{
  "count": 150,
  "next": "/api/v1/risks/?page=2",
  "previous": null,
  "results": [...]
}
```

---

## Resolved Clarifications

| Topic | Resolution |
|-------|------------|
| API Framework | Django REST Framework 3.15+ |
| Key Storage | SHA-256 hash, prefix for lookup |
| Soft Delete | `deleted_at` timestamp pattern |
| Audit Storage | JSON fields for state snapshots |
| STRIDE Storage | PostgreSQL ArrayField |
| Pagination | 50 items default, standard DRF pagination |

## Dependencies to Add

```toml
# Add to pyproject.toml [project.dependencies]
"djangorestframework>=3.15.0"
```

No other new dependencies required. All other functionality uses Django built-ins.
