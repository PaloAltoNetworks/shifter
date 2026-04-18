# Shifter Architecture Assessment

**Date:** 2026-02-07 | **Rating: GOOD (7.5/10)** | **Trajectory: Stable with localized debt**

---

## Executive Summary

Shifter's architecture is fundamentally sound for its current scale. The Django monorepo cleanly separates seven apps (CMS, Engine, Mission Control, Management, Risk Register, Documentation, Shared) with well-defined service layer boundaries. The dual-library approach (cyberscript for cross-service contracts, shared for Django integration) is a mature pattern. The event-driven provisioner communication via SNS/SQS is correctly designed.

However, there are two systemic architectural problems: (1) the provisioner has drifted from its own patterns, concentrating logic in a 2,911-line main.py that bypasses the Orchestrator/Plan/Executor abstractions it defines, and (2) the platform's CMS services.py at 3,440 lines is a god-service that conflates six distinct domains.

The architecture supports the current user base but the provisioner's coupling to Django's database schema (raw SQL against Django tables) creates a ticking time bomb for any schema evolution.

---

## Systemic Patterns

### What Works Well

**1. Service Layer as API Boundary**
Every Django app exposes a stateless service module. Views never touch models directly. This is consistently applied across CMS, Engine, and Management. The `__init__.py` lazy-loading pattern prevents circular imports while providing clean public APIs. This is textbook Django architecture.

**2. Pydantic as the Contract Language**
From CyberScript schemas through Django shared schemas to provisioner config dataclasses, Pydantic models serve as the universal data contract. This creates type safety at every boundary crossing: user input -> view -> service -> model -> event -> provisioner.

**3. Soft Delete Everywhere**
The `EntityBase.save()` method auto-sets `deleted_at` on terminal statuses. Custom managers filter deleted records. This is applied consistently across CMS and Engine models, providing an audit trail without sacrificing query ergonomics.

**4. Event-Driven Decoupling**
Provisioner publishes events to SNS; platform handlers subscribe via SQS. Events are notification-only (state written to DB first), which prevents event-driven data corruption. Three separate handler modules (engine, CMS, mission_control) consume events independently.

**5. WebSocket "Hydrate + Stream" Pattern**
All three WebSocket consumers (SSH, RangeStatus, NGFWStatus) send current state on connect, then stream deltas. This eliminates the stale-state-on-reconnect class of bugs.

### What Doesn't Work

**1. Provisioner/Platform Coupling via Raw SQL**
The provisioner (`main.py:274-302`) executes `UPDATE mission_control_range SET...` directly against Django tables. This means:
- Django model changes silently break the provisioner (no migration coordination)
- Django ORM validation is bypassed (data integrity at risk)
- The provisioner is not independently deployable
- Schema changes require coordinated deploys

This is the single most consequential architectural issue. The fix is event-carried state transfer: provisioner should only write to IaC state and publish events; platform handlers update Django models.

**2. Mixed IaC Strategy (Pulumi + Terraform)**
Ranges use both Pulumi (`stacks/range_stack.py`) and Terraform (`range_terraform_runner.py`), with runtime detection (`has_terraform_state()`) to decide which tool to use. NGFWs use Terraform exclusively. This creates operational complexity, state management confusion, and makes it hard to reason about what manages what.

**3. God Objects: main.py and services.py**
`main.py` (2,911 lines) concentrates provisioning orchestration, DB access, IaC execution, and NGFW configuration. It bypasses its own Orchestrator/Plan/Executor abstractions ~40% of the time. `cms/services.py` (3,440 lines) handles agents, credentials, scenarios, ranges, NGFWs, and storage in a single file.

**4. Dual Request Models with UUID Correlation**
CMS and Engine each maintain their own Request model, correlated only by `request_id` UUID. There's no single source of truth for request lifecycle, and desync is possible if events are missed.

---

## Architecture by Boundary

### Django Platform (Rating: 8.5/10)
Clean app isolation, excellent use of Django features (custom managers, abstract bases, JSONField for flexible schemas, `select_for_update` for concurrency). The shared/cyberscript dual-library is well-designed. Auth architecture (OIDC with Cognito, dev bypass guarded by DEBUG) is sound. WebSocket architecture is focused and well-scoped.

**Key debt:** CMS services.py needs decomposition into domain modules.

### Provisioner (Rating: 6/10)
Excellent architectural *bones* (Orchestrator/Plan/Executor/Component pattern) but poor discipline in following them. main.py is where "quick fixes" go to die. The migration from Pulumi to Terraform is incomplete. Direct DB access creates tight coupling.

**Key debt:** main.py refactoring, complete Terraform migration, decouple from Django DB.

### Cross-Boundary (Rating: 6.5/10)
SNS/SQS event system is well-designed but lacks schema versioning and DLQ monitoring. No event duplication handling (SQS at-least-once). Provisioner reads from Django DB directly (should use events). Frontend is vanilla JS with monolithic class design - functional but not scalable.

**Key debt:** Add schema versioning, implement idempotent event handling, decouple provisioner DB reads.

### Frontend (Rating: 5/10)
Vanilla JS with `DashboardManager` class handling all UI state. No framework, no component model, manual DOM manipulation. WebSocket integration works but has no reconnection backoff. Adequate for current scope but will become a bottleneck if UI complexity grows.

---

## Recommendations

### P0 - Critical (blocks scaling)
1. **Decouple provisioner from Django DB** - Move to event-carried state transfer
2. **Refactor provisioner main.py** - Extract into services/workflows, target <500 LOC per file
3. **Complete Terraform migration** - Eliminate Pulumi, remove dual-IaC confusion

### P1 - High (creates friction)
4. **Split cms/services.py** into domain modules (agents, credentials, scenarios, ranges, ngfws, storage)
5. **Add event schema versioning** - Deploy handlers first, then provisioner changes
6. **Deduplicate handler code** - engine/handlers.py and mission_control/handlers.py share identical `process_event()` and `parse_sns_message()`

### P2 - Medium (technical debt)
7. Document the Request correlation protocol between CMS and Engine
8. Add DLQ monitoring and alerting for failed event processing
9. Reorganize provisioner plans into namespaced directories (setup/, ops/, ngfw/)

---

## Raw Data
- Platform architecture details: `temp/raw-arch-platform.md`
- Provisioner architecture details: `temp/raw-arch-provisioner.md`
