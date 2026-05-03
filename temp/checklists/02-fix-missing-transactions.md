# Checklist: Add `transaction.atomic()` to CMS Multi-Step Operations

**Priority:** CRITICAL | **Effort:** Medium (4-6 hours) | **Risk if deferred:** Orphaned DB records on partial failure

---

## Context

`cms/services.py` (3,440 lines, 38 functions) has **zero** uses of `transaction.atomic()`. Multi-step operations that create/modify multiple DB records have no rollback protection. If a failure occurs mid-operation, the database is left in an inconsistent state with orphaned records.

In contrast, `engine/services.py` uses `transaction.atomic()` and `select_for_update()` correctly throughout, proving the team knows the pattern.

**Highest-risk functions** (multiple DB writes with no atomicity):
- `create_range()` (line 1391, ~208 LOC) - Creates Request, RangeInstance, App records, then calls Engine
- `create_ngfw()` (line 3193) - Creates Request, Instance, App records, then calls Engine
- `destroy_range()` (line 1602) - Updates status, then calls Engine destroy
- `destroy_ngfw()` (line 3360) - Updates status, then calls Engine destroy
- `create_credential()` (line 481) - Creates CredentialType + Credential records
- `complete_upload()` (line 2642) - Updates AgentConfig status + metadata

---

## Pre-Work

- [ ] Read `engine/services.py` to understand the existing `transaction.atomic()` usage patterns in this codebase
- [ ] Read `cms/services.py` imports section (lines 1-40) - confirm `django.db.transaction` is NOT currently imported
- [ ] Read each of the six high-risk functions listed above to understand their DB write sequences
- [ ] For each function, identify the exact failure points where partial writes would cause data corruption
- [ ] Identify which functions call external services (Engine) AFTER DB writes - these need careful transaction boundary placement

## Implementation: Priority 1 - Multi-Record Creates

### `create_range()` (~line 1391)
- [ ] Read the full function
- [ ] Identify all ORM `.create()`, `.save()`, and `.filter().update()` calls
- [ ] Map the sequence: Request create -> RangeInstance create -> App create -> engine_create_range call
- [ ] Wrap the DB operations in `transaction.atomic()`, but **keep the Engine call OUTSIDE** the transaction (external service calls inside transactions hold DB locks too long)
- [ ] Pattern should be:
    ```python
    with transaction.atomic():
        request = ...create(...)
        range_instance = ...create(...)
        app = ...create(...)
    # Outside transaction - if Engine fails, records exist but are in 'pending' status
    engine_create_range(...)
    ```
- [ ] Verify the range status lifecycle handles Engine failure gracefully (pending -> failed)

### `create_ngfw()` (~line 3193)
- [ ] Read the full function
- [ ] Same pattern: wrap DB creates in `transaction.atomic()`, keep Engine call outside
- [ ] Identify all three DB records created and ensure they're all inside the boundary

### `create_credential()` (~line 481)
- [ ] Read the full function
- [ ] Wrap the CredentialType + Credential creation in `transaction.atomic()`
- [ ] This one is pure DB - no external service calls, so the entire operation can be atomic

## Implementation: Priority 2 - Status Transitions

### `destroy_range()` (~line 1602)
- [ ] Read the full function
- [ ] Identify the status update + Engine destroy call sequence
- [ ] Wrap status update in `transaction.atomic()` with `select_for_update()` to prevent concurrent destroys
- [ ] Keep Engine call outside the transaction

### `destroy_ngfw()` (~line 3360)
- [ ] Same pattern as `destroy_range()`
- [ ] Add `select_for_update()` on the App record before status transition

### `pause_range()` (~line 2012) and `resume_range()` (~line 2229)
- [ ] Read both functions
- [ ] Wrap status transitions in `transaction.atomic()`
- [ ] These call Engine, so keep external calls outside

## Implementation: Priority 3 - Remaining Functions

### `complete_upload()` (~line 2642)
- [ ] Read the function
- [ ] Wrap AgentConfig status + metadata updates in `transaction.atomic()`

### `delete_agent()` (~line 122)
- [ ] Check if it does multiple DB operations that need atomicity

### `delete_credential()` (~line 602)
- [ ] Check if it does multiple DB operations that need atomicity

## Add the Import

- [ ] Add `from django.db import transaction` to imports section
- [ ] Verify no circular import issues

## Verification

- [ ] Run the full platform test suite: `cd shifter_platform && TESTING=1 python -m pytest`
- [ ] Search for any test that simulates mid-operation failure - if none exist, note this as a gap (don't write them in this PR)
- [ ] Grep `cms/services.py` for `transaction.atomic` and confirm all multi-write functions are covered
- [ ] Review each `transaction.atomic()` boundary to ensure no external service calls (Engine, S3, SNS) are inside the transaction
- [ ] Verify no `select_for_update()` calls exist without a surrounding `transaction.atomic()` (Django requirement)

## Anti-Patterns to Avoid

- [ ] Do NOT wrap entire functions in `transaction.atomic()` if they contain external service calls
- [ ] Do NOT use `transaction.on_commit()` for the Engine calls unless you need to guarantee DB commit before the call (evaluate case by case)
- [ ] Do NOT add transactions to pure-read functions (list_*, get_*) - they don't need them
- [ ] Do NOT use nested `transaction.atomic()` (savepoints) unless specifically required for partial rollback
