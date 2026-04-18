# Shifter Platform Foundation Architecture Review

## 1. Summary

**Overall Rating: Good**

The Shifter platform demonstrates a well-thought-out Django architecture with clear separation of concerns, strong service layer patterns, and thoughtful abstraction boundaries. The platform successfully manages the inherent complexity of a multi-user cyber range system while maintaining clean interfaces between components.

The architecture shows maturity in several areas: dedicated shared library for cross-cutting concerns, consistent use of Pydantic schemas for data contracts, proper soft-delete patterns, and well-isolated Django apps. The dual-library approach (cyberscript + shared) creates some redundancy but appears intentional for decoupling Django from the core domain logic.

The primary architectural weakness is the 3,440-line CMS services.py file, which has grown into a "god service" that handles too many responsibilities. The engine models also show legacy field accumulation that could benefit from refactoring. These are moderate technical debt items rather than critical flaws.

## 2. Strengths

### 2.1 Clean App Boundaries
- **Seven well-defined Django apps** with clear responsibilities:
  - `cms/`: Content management (scenarios, assets, credentials)
  - `engine/`: Infrastructure lifecycle (ranges, NGFW, provisioning)
  - `mission_control/`: Presentation layer (views, WebSockets, UI)
  - `management/`: Platform administration (users, activity logs)
  - `risk_register/`: Security risk tracking (standalone module)
  - `documentation/`: Documentation app
  - `shared/`: Cross-cutting contracts and schemas
- **No circular dependencies detected** - apps depend on shared/cyberscript but not on each other at the model level
- CMS and Engine properly isolated via service layer APIs (lines `cms/__init__.py:26-56`)

### 2.2 Dual-Library Architecture (cyberscript + shared)
- **cyberscript/** is a standalone library with:
  - Pydantic schemas (RangeSpec, InstanceSpec, AppSpec, etc.)
  - Shared enums (ResourceStatus, RequestType)
  - Exception hierarchy (CMSError, ProvisioningError, AssetError)
  - Zero Django dependencies - can be used by provisioner
- **shared/** is a Django app that re-exports cyberscript:
  - Provides Django integration point
  - Maintains backward compatibility for Django imports
  - Acts as facade over cyberscript (lines `shared/__init__.py:8-34`)
- **Design rationale**: Allows provisioner (non-Django) and platform (Django) to share contracts without coupling

### 2.3 Service Layer Pattern
- **Consistent stateless service modules** across apps:
  - `cms/services.py`: 3,440 lines, 36+ public functions (from `__all__`)
  - `engine/services.py`: 993 lines, 11 functions exposed via `__init__.py`
  - `management/services.py`: 186 lines, 6 focused utility functions
- **Proper separation** of business logic from views/models
- **Type hints throughout** with TYPE_CHECKING guards for forward references
- **Comprehensive validation** in service entry points

### 2.4 Model Layer Design
- **Abstract bases provide consistency**:
  - `CatalogBase` for system-defined types (scenarios, credential types)
  - `EntityBase` for user-owned entities (instances, apps)
  - `Instantiation` for materialized infrastructure
- **Soft delete pattern** implemented consistently across models:
  - `deleted_at` timestamp field
  - `is_deleted` property
  - Auto-soft-delete on terminal statuses (lines `cms/models.py:783-808`)
- **Smart use of Django features**:
  - Custom managers (`ActiveRangeInstanceManager`)
  - JSONField for flexible specs/state storage
  - db_index on frequently queried fields
  - Select_for_update for subnet allocation

### 2.5 Auth & Middleware
- **Clean dev/prod separation** (`config/settings.py:78-81`):
  - DEBUG mode: dev_login bypass
  - Production: OIDC with Cognito
  - Security checks prevent dev auth in production
- **Minimal custom middleware**: Only HealthCheckMiddleware for ALB bypass
- **Custom OIDC backend** stores Cognito sub in UserProfile for MCP lookups

### 2.6 WebSocket Architecture
- **Three focused consumers** (`mission_control/consumers.py:20-356`):
  - SSHConsumer: Terminal connections with async SSH bridging
  - RangeStatusConsumer: Real-time range lifecycle updates
  - NGFWStatusConsumer: NGFW provisioning progress
- **"Hydrate on connect, stream deltas" pattern**: Immediately sends current state on connect, then streams updates
- **Proper error codes**: Custom WebSocketCloseCode enum (4001-4503)
- **Channel groups** abstracted via cyberscript utility functions

### 2.7 Configuration Management
- **Well-organized settings.py** (445 lines):
  - Logical sections with clear comments
  - Environment-aware configuration (dev/test/prod)
  - Security settings conditional on DEBUG
  - Comprehensive AWS service configuration
- **ECS logging with custom formatter** (`config/logging.py:24-113`):
  - Elastic Common Schema (ECS) 8.11 compliant
  - Structured JSON for XDR/XSIAM ingestion
  - HTTP request context injection

## 3. Critical Issues

**None identified.** No blocking architectural problems that would prevent scaling or cause serious production issues.

## 4. Moderate Issues

### 4.1 God Service: cms/services.py (3,440 lines)
**Location**: `cms/services.py`

Single service file handles all CMS responsibilities: Agent management, Credential management, Scenario management, Range orchestration, NGFW management, Storage management.

**Impact**: Hard to navigate, merge conflicts likely, difficult to test, high cognitive load.

**Recommendation**: Split into domain modules (agents.py, credentials.py, scenarios.py, ranges.py, ngfws.py, storage.py).

### 4.2 Legacy Field Accumulation in Range Model
**Location**: `engine/models.py:188-557`

Range model mixes v1 (Lambda) and v2 (Pulumi) provisioner fields. Legacy fields: `victim_ip`, `kali_ip`, `victim_instance_id`, etc. New fields: `provisioned_instances` JSON, `pulumi_stack`.

**Impact**: Model bloat (370 lines), unclear which fields are active, potential for stale data.

### 4.3 Dual Import Paths for Shared Code
Same concepts importable from two places (`shared.enums` vs `cyberscript.enums`).

### 4.4 IntegerField FKs for Cross-App References
`RangeInstance` stores `user_id` and `range_id` as IntegerField instead of FK. No referential integrity at DB level.

### 4.5 Multiple Request Models
Two separate Request models (CMS and Engine), correlated by `request_id` UUID only. No single source of truth for request lifecycle.

## 5. Minor Issues

- Inconsistent verbose names across models
- Magic numbers in constants without business rationale documentation
- Dual exception hierarchies (shared vs cms)
- No explicit API versioning for REST Framework

## 6. Patterns Observed

### Good Patterns
1. **Lazy loading in __init__.py** - Prevents circular imports
2. **Consistent validation in service entry points**
3. **Soft delete with invariant enforcement**
4. **TYPE_CHECKING guards**
5. **Custom managers for active records**
6. **JSONField for flexible schemas**
7. **Atomic transactions for consistency**

### Recurring Design Decisions
1. Pydantic for data contracts
2. UUIDs for correlation
3. String enums for JSON serialization
4. Soft delete everywhere
5. Service layer as API boundary

## 7. Architecture Scorecard

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Modularity** | 8/10 | Clean app boundaries, one god service |
| **Testability** | 8/10 | Service layer enables testing, but 3k LOC file is hard to test |
| **Scalability** | 9/10 | Good use of indexes, select_for_update, atomic transactions |
| **Maintainability** | 7/10 | Excellent patterns, but large files reduce clarity |
| **Security** | 9/10 | Auth well-designed, soft delete preserves audit trail |
| **Documentation** | 8/10 | Inline docs excellent, architectural docs could improve |
| **Type Safety** | 9/10 | Comprehensive type hints, Pydantic validation |
| **Django Best Practices** | 9/10 | Proper use of ORM, managers, middleware, signals |

**Overall: 8.3/10 (Good)**
