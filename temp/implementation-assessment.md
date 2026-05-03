# Shifter Implementation Quality Assessment

**Date:** 2026-02-07 | **Rating: ADEQUATE (6.5/10)** | **Trajectory: Needs targeted investment**

---

## Executive Summary

Shifter's implementation quality varies significantly by subsystem. The scenario processing pipeline (schema, loader, hydrator) is excellent. The engine's SSH handling and transaction management are production-quality. The asset/upload subsystem demonstrates good security awareness with HMAC tokens and magic byte validation.

However, the two largest files in the codebase - `cms/services.py` (3,440 lines) and `provisioner/main.py` (2,911 lines) - both exhibit serious implementation quality problems: extreme code duplication, missing transaction boundaries, over-defensive programming against impossible conditions, and functions exceeding 200 lines. These aren't just style issues - the missing `transaction.atomic()` in CMS multi-step operations and bare `except Exception` blocks in the provisioner represent real data corruption and silent failure risks.

---

## Cross-Cutting Implementation Issues

### 1. Defensive Programming Against the Framework (CMS)

The CMS services.py contains **27 repetitions** of the same 15-line user validation block, totaling 300+ lines of pure boilerplate:
```python
if user is None: ...
if not hasattr(user, "id"): ...
if user.id is None: ...
```

Worse, it validates ORM return values against impossible conditions: `if agent is None` after `AgentConfig.objects.get()` (Django raises `DoesNotExist`, never returns `None`). This pattern adds ~65 lines of dead validation per function.

**Impact:** Maintenance burden, cognitive load, and false confidence. The real validation gaps (missing `transaction.atomic()`) go unaddressed while energy is spent on impossible error paths.

**Fix:** One decorator replaces 300+ lines of boilerplate. Remove impossible ORM checks.

### 2. Missing Transaction Management (CMS - Critical)

Zero uses of `@transaction.atomic` in the entire 3,440-line CMS services.py. Multi-step operations like `create_range()` (creates Request, RangeInstance, App, then calls Engine) and `create_ngfw()` (creates 3 DB records + calls external service) have no rollback safety. Failure midway leaves orphaned records.

In contrast, `engine/services.py` uses `transaction.atomic()` and `select_for_update()` correctly throughout. This inconsistency suggests the patterns are known but not uniformly applied.

### 3. Function Gigantism (Both CMS and Provisioner)

| Function | LOC | File |
|----------|-----|------|
| `create_range()` | 208 | cms/services.py |
| `_run_provision()` | 168 | provisioner/main.py |
| `_run_single_instance_setup()` | 150 | provisioner/main.py |
| `get_active_range()` | 128 | cms/services.py |
| `_run_terraform_provision()` | 121 | provisioner/main.py |
| `list_agents()` | 110 | cms/services.py |

Functions this large are untestable without massive mocking, hard to reason about, and breed bugs in rarely-executed branches.

### 4. Code Duplication Across Boundaries

- **Handler code:** `engine/handlers.py` and `mission_control/handlers.py` share identical `process_event()` and `parse_sns_message()` implementations. Complete copy-paste.
- **ECS task starters:** `_start_ecs_task()`, `_start_range_ecs_task()`, and `_start_ngfw_ecs_task()` in `engine/ecs.py` are nearly identical 100-line functions.
- **DB connection logic:** Duplicated across provisioner `main.py`, `config.py`, and `components/network.py`.
- **NGFW status checking:** Repeated pattern across 3+ locations in provisioner.

### 5. Inconsistent Error Handling

The provisioner uses a mix of:
- Bare `except Exception` (15+ instances) that swallow errors
- Specific exception handling (in executors - done well)
- Error message truncation to 1000 chars (losing debugging info)

The CMS uses a mix of:
- `DoesNotExist` -> `CMSError` conversion (good, but inconsistent)
- Generic `except Exception` blocks that hide real errors
- Silent `return None` on error in handlers

The engine handlers have "audit-only" handlers registered that only log - unclear why they exist in the event routing.

---

## Subsystem Quality

### Excellent (9/10)
- **Scenario processing** (`cms/scenarios/`): Clean Pydantic models, `@lru_cache` for loading, focused hydration functions. Average 10 lines per function.
- **Engine SSH** (`engine/ssh.py`): Proper async context manager, excellent exception hierarchy, resource cleanup even on failure.
- **Guacamole integration** (`mission_control/guacamole.py`): Correct HMAC-SHA256 + AES-128-CBC per spec, proper crypto primitives.
- **Upload token security** (`cms/assets/upload_token.py`): HMAC signing, timing-safe comparison, time-based expiry.

### Good (7-8/10)
- **Engine services** (`engine/services.py`): Proper `transaction.atomic()` and `select_for_update()`. Hardcoded RDP passwords (TODO #542) are the main wart.
- **CMS models** (`cms/models.py`): Clean abstract base hierarchy, proper custom `save()` methods, good constraints.
- **Asset validation** (`cms/assets/validation.py`): Defense in depth with size, extension, and magic byte checks.
- **Provisioner executors** (`executors/`): Clean protocol-based design, consistent `CommandResult` interface, proper timeout handling (SSM especially good).
- **Provisioner events** (`events.py`): Single responsibility, consistent envelope pattern, proper error handling.

### Adequate (5-6/10)
- **Mission Control views** (`mission_control/views.py`): Inconsistent error response formats, type conversions without try/except, 4x duplicated request_id/range_id handling.
- **Provisioner orchestrators**: Good protocol design but `_execute_step()` is 189 lines with deep nesting. Commit checking uses hardcoded string matching.
- **CMS handlers**: Clean routing but silent failures (returns None on error), bare exception handlers too broad.
- **Engine handlers**: Same issues as CMS handlers, plus duplicate code.

### Needs Work (3-4/10)
- **CMS services** (`cms/services.py`): 300+ lines of duplicate validation, zero transaction management, impossible ORM checks, 36 functions averaging 95 lines each.
- **Provisioner main** (`main.py`): 2,911-line god object, bare `except Exception` blocks, dynamic SQL column construction, functions bypassing orchestrator pattern.
- **Provisioner range_ops** (`range_ops.py`): Complex pause/resume with scattered DB queries, no transaction management, hardcoded retry logic.

---

## Top Recommendations (Ordered by Impact)

### Critical - Data Integrity Risk
1. **Add `transaction.atomic()` to CMS multi-step operations** - `create_range()`, `create_ngfw()`, and other multi-write functions have no rollback protection. This is the highest-impact fix for the least effort.

2. **Replace bare `except Exception` in provisioner** - 15+ locations swallow all errors including logic bugs. Replace with specific exception types.

### High - Maintainability
3. **Extract user validation to a decorator in CMS** - Eliminates 300+ duplicate lines across 27 functions.

4. **Deduplicate handler code** - Extract shared `process_event()` and `parse_sns_message()` to `shared/handlers.py`.

5. **Deduplicate ECS task starters** - Extract common logic from three 100-line near-identical functions.

### Medium - Code Health
6. **Break down god functions** - Target <50 lines per function in services and provisioner.

7. **Remove impossible ORM validation** - Trust Django's guarantees. Delete `if result is None` checks after `.get()` calls.

8. **Standardize error response format in views** - Define a consistent JSON error envelope.

9. **Move hardcoded credentials to settings** - Complete TODO #542 in engine/services.py.

10. **Add channel layer error handling in mission_control handlers** - Redis down currently causes silent failure.

---

## Raw Data
- CMS implementation details: `temp/raw-impl-cms.md`
- Engine/Mission Control details: `temp/raw-impl-engine-mc.md`
- Provisioner details: `temp/raw-impl-provisioner.md`
