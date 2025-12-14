# Data Model: Risk Register

**Feature**: 001-risk-register
**Date**: 2025-12-13

## Entity Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    Risk     │────<│   Comment   │     │   APIKey    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────┐
│                      AuditLog                        │
│  (polymorphic: tracks changes to all entities)       │
└─────────────────────────────────────────────────────┘
```

## Entities

### Risk

The central entity representing a security risk.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | BigAutoField | PK | Primary key |
| title | CharField(200) | Required | Short title for the risk |
| description | TextField | Required | Detailed description |
| severity | CharField(10) | Required, choices | critical/high/medium/low |
| status | CharField(20) | Required, choices | open/acknowledged/mitigating/resolved/closed |
| stride_categories | ArrayField(CharField) | Optional | List of STRIDE categories (S/T/R/I/D/E) |
| likelihood_score | PositiveSmallIntegerField | Optional, 1-5 | Likelihood rating |
| impact_score | PositiveSmallIntegerField | Optional, 1-5 | Impact rating |
| attack_vector | TextField | Optional | Description of attack vector |
| affected_assets | TextField | Optional | Assets/components affected |
| mitigation_status | TextField | Optional | Current mitigation efforts |
| resolution_reason | TextField | Optional | Reason for closure |
| created_at | DateTimeField | Auto | Creation timestamp |
| updated_at | DateTimeField | Auto | Last update timestamp |
| deleted_at | DateTimeField | Nullable | Soft delete timestamp |

**Choices**:
```python
class Severity(models.TextChoices):
    CRITICAL = 'critical', 'Critical'
    HIGH = 'high', 'High'
    MEDIUM = 'medium', 'Medium'
    LOW = 'low', 'Low'

class Status(models.TextChoices):
    OPEN = 'open', 'Open'
    ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
    MITIGATING = 'mitigating', 'Mitigating'
    RESOLVED = 'resolved', 'Resolved'
    CLOSED = 'closed', 'Closed'

class StrideCategory(models.TextChoices):
    SPOOFING = 'S', 'Spoofing'
    TAMPERING = 'T', 'Tampering'
    REPUDIATION = 'R', 'Repudiation'
    INFO_DISCLOSURE = 'I', 'Information Disclosure'
    DENIAL_OF_SERVICE = 'D', 'Denial of Service'
    ELEVATION = 'E', 'Elevation of Privilege'
```

**Validation Rules**:
- Title: 1-200 characters
- Severity: Must be valid choice
- Status: Must be valid choice
- Likelihood/Impact scores: 1-5 inclusive, or null
- STRIDE categories: Each must be valid single-char code

**Computed Properties**:
- `is_deleted`: True if `deleted_at` is not null
- `risk_score`: `likelihood_score * impact_score` (if both set)
- `comment_count`: Count of non-deleted comments

---

### Comment

A timestamped note attached to a Risk.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | BigAutoField | PK | Primary key |
| risk | ForeignKey(Risk) | Required | Parent risk |
| content | TextField | Required | Comment text |
| author_user | ForeignKey(User) | Nullable | Human author (if UI) |
| author_apikey | ForeignKey(APIKey) | Nullable | API key author (if API) |
| parent_comment | ForeignKey(self) | Nullable | Previous version if edit |
| created_at | DateTimeField | Auto | Creation timestamp |
| deleted_at | DateTimeField | Nullable | Soft delete timestamp |

**Validation Rules**:
- Content: 1+ characters, no max limit
- Exactly one of `author_user` or `author_apikey` must be set
- `parent_comment` only set for edit versions

**Constraints**:
- Comments are immutable: edits create new Comment with `parent_comment` reference
- Deletes are soft-deletes

---

### APIKey

Credential for programmatic access.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | BigAutoField | PK | Primary key |
| name | CharField(100) | Required | Human-friendly name |
| prefix | CharField(8) | Required, unique | Key prefix for identification |
| key_hash | CharField(64) | Required | SHA-256 hash of full key |
| created_by | ForeignKey(User) | Required | User who created the key |
| created_at | DateTimeField | Auto | Creation timestamp |
| last_used_at | DateTimeField | Nullable | Last successful authentication |
| expires_at | DateTimeField | Nullable | Optional expiry |
| revoked_at | DateTimeField | Nullable | Revocation timestamp |

**Validation Rules**:
- Name: 1-100 characters
- Prefix: Exactly 8 characters, alphanumeric
- Key hash: Exactly 64 characters (SHA-256 hex)

**Key Format**:
```
rr_live_<32-random-chars>
└─prefix─┘
```

**Computed Properties**:
- `is_active`: True if not revoked and not expired
- `display_key`: `{prefix}...` (for admin listing)

---

### AuditLog

Record of a state change.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | BigAutoField | PK | Primary key |
| entity_type | CharField(20) | Required | 'risk', 'comment', 'apikey' |
| entity_id | PositiveIntegerField | Required | ID of affected entity |
| action | CharField(20) | Required | Action type (see below) |
| actor_type | CharField(10) | Required | 'user' or 'apikey' |
| actor_id | PositiveIntegerField | Required | ID of actor |
| timestamp | DateTimeField | Auto | When action occurred |
| previous_state | JSONField | Nullable | State before action |
| new_state | JSONField | Nullable | State after action |
| context | TextField | Optional | Reason or notes |

**Action Types**:
- `create`: Entity created
- `update`: Entity modified
- `delete`: Entity soft-deleted
- `restore`: Entity restored from deletion
- `close`: Risk closed
- `reopen`: Risk reopened

**Note**: Actor is denormalized (type + id) rather than polymorphic FK for query simplicity.

---

## Relationships

```
Risk (1) ─────< Comment (many)
    │
    └── Comments belong to exactly one Risk
        Cascade delete when Risk is deleted

User (1) ─────< APIKey (many)
    │
    └── User can create multiple API keys
        SET_NULL on user deletion (key stays for audit)

User/APIKey (1) ─────< Comment (many)
    │
    └── One author type per comment
        SET_NULL on deletion (comment stays for audit)

All Entities ─────< AuditLog (many)
    │
    └── Polymorphic via entity_type + entity_id
        No cascade (audit log is permanent)
```

## State Transitions

### Risk Status

```
                    ┌───────────┐
                    │   OPEN    │ (initial)
                    └─────┬─────┘
                          │
                          ▼
                ┌─────────────────┐
                │  ACKNOWLEDGED   │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │   MITIGATING    │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │    RESOLVED     │
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │     CLOSED      │
                └─────────────────┘

Note: Any status can transition to any other status.
Linear flow is recommended but not enforced.
All transitions logged in AuditLog.
```

### APIKey Lifecycle

```
┌──────────┐     revoke()     ┌──────────┐
│  ACTIVE  │ ───────────────> │ REVOKED  │
└──────────┘                  └──────────┘
     │
     │ (time passes)
     ▼
┌──────────┐
│ EXPIRED  │ (if expires_at set)
└──────────┘
```

## Indexes

Recommended indexes for query performance:

```python
class Risk:
    class Meta:
        indexes = [
            models.Index(fields=['status', 'deleted_at']),
            models.Index(fields=['severity', 'deleted_at']),
            models.Index(fields=['created_at']),
        ]

class Comment:
    class Meta:
        indexes = [
            models.Index(fields=['risk', 'deleted_at', 'created_at']),
        ]

class APIKey:
    class Meta:
        indexes = [
            models.Index(fields=['prefix']),  # For auth lookup
            models.Index(fields=['created_by', 'revoked_at']),
        ]

class AuditLog:
    class Meta:
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['actor_type', 'actor_id']),
            models.Index(fields=['timestamp']),
        ]
```
