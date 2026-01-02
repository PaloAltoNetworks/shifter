# Shifter Engine Refactor Plan

## Issue #437: Implement Shifter Engine Services

### Objective
Refactor Shifter Engine to align with the new service architecture. By completion:
1. Engine's services are fully implemented
2. NO engine concerns remain in Mission Control's views or elsewhere
3. Models are in correct locations per architecture
4. Service boundaries are respected

---

## Current State Analysis

### Service Boundary Violations Found

| Violation | Location | Should Be |
|-----------|----------|-----------|
| `Range` model | `mission_control/models.py:73` | `engine/models.py` |
| `UserNGFW` model | `mission_control/models.py:14` | `engine/models.py` |
| ECS service (`start_provisioning`, `start_teardown`, `get_task_status`) | `mission_control/services/engine.py` | `engine/services/ecs.py` |
| SSH service (`SSHConnection`) | `mission_control/services/ssh.py` | `engine/services/ssh.py` |
| Secrets service (`get_ssh_key`) | `mission_control/services/secrets.py` | `engine/services/secrets.py` |
| NGFW views/API (12 functions) | `mission_control/views.py:638-1049` | `engine/api/ngfw.py` |
| Range API views | `mission_control/views.py:481-604` | Already delegating to engine services |
| Terminal view | `mission_control/views.py:176-193` | Uses Range model directly |

### Current Engine Structure

```
engine/
├── __init__.py                    # Empty
├── apps.py                        # Django app config
├── services.py                    # Stub interface (NotImplementedError stubs)
└── services/
    ├── __init__.py                # create_range stub
    ├── allocation.py              # allocate_subnet_index (imports mission_control.models.Range)
    ├── orchestration.py           # launch/cancel/destroy (imports mission_control.models.Range)
    ├── scenarios.py               # get_scenario_config, validate_launch
    └── serialization.py           # range_to_dict (imports mission_control.models.Range)
```

### Target Architecture (per engine.md)

```
engine/
├── __init__.py
├── apps.py
├── models.py                      # Range, UserNGFW (moved from mission_control)
├── services/
│   ├── __init__.py                # Public service interface
│   ├── allocation.py              # Subnet allocation
│   ├── orchestration.py           # Range lifecycle (launch/cancel/destroy)
│   ├── scenarios.py               # Scenario validation
│   ├── serialization.py           # DTOs
│   ├── ecs.py                     # ECS Fargate task execution (from MC)
│   ├── ssh.py                     # Async SSH connection (from MC)
│   └── secrets.py                 # AWS Secrets Manager (from MC)
└── api/                           # REST API endpoints (optional - could stay in MC)
    ├── __init__.py
    └── ngfw.py                    # NGFW API endpoints
```

---

## Phased Implementation Plan

### Phase 1: Move Models to Engine (Foundation)

This is the foundation - all other phases depend on models being in the right place.

#### Phase 1.1: Move Range model to engine

☐ Phase 1.1 PREP: Read tdd-plan.md and django-testing.md skills
☐ Phase 1.1 RED: Write failing tests for Range model import from engine.models
    - Test file: `tests/test_engine_models.py`
    - Test: `TestRangeModel::test_range_importable_from_engine`
    - Test: `TestRangeModel::test_range_status_enum`
    - Test: `TestRangeModel::test_get_active_for_user`
    - Test: `TestRangeModel::test_get_destroyable_for_user`
    - Test: `TestRangeModel::test_allocate_subnet_index`
    - Test: `TestRangeModel::test_terminal_statuses`
    - Test: `TestRangeModel::test_cancellable_statuses`
☐ Phase 1.1 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_models.py::TestRangeModel -v`, confirm ImportError
☐ Phase 1.1 GREEN: Move Range model from mission_control/models.py to engine/models.py
    - Create `engine/models.py` with Range model
    - Update imports in engine/services/*.py
    - Add re-export in mission_control/models.py for backwards compat during migration
☐ Phase 1.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_models.py::TestRangeModel -v`, confirm pass

#### Phase 1.2: Move UserNGFW model to engine

☐ Phase 1.2 PREP: Read tdd-plan.md
☐ Phase 1.2 RED: Write failing tests for UserNGFW model import from engine.models
    - Test file: `tests/test_engine_models.py`
    - Test: `TestUserNGFWModel::test_userngfw_importable_from_engine`
    - Test: `TestUserNGFWModel::test_userngfw_status_enum`
    - Test: `TestUserNGFWModel::test_active_for_user`
☐ Phase 1.2 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_models.py::TestUserNGFWModel -v`, confirm ImportError
☐ Phase 1.2 GREEN: Move UserNGFW model from mission_control/models.py to engine/models.py
    - Add UserNGFW to engine/models.py
    - Update Range.ngfw FK to use engine.UserNGFW
    - Add re-export in mission_control/models.py for backwards compat during migration
☐ Phase 1.2 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_models.py::TestUserNGFWModel -v`, confirm pass

#### Phase 1.3: Create and run migrations

☐ Phase 1.3 PREP: Read django-testing.md
☐ Phase 1.3 GREEN: Create migration to move models
    - Run `uv run python manage.py makemigrations engine`
    - Run `uv run python manage.py makemigrations mission_control`
    - Verify migration files created
☐ Phase 1.3 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_models.py -v`, confirm all pass

#### Phase 1.4: Update all internal imports

☐ Phase 1.4 PREP: Read tdd-plan.md
☐ Phase 1.4 GREEN: Update imports in engine/services/*.py
    - `allocation.py`: Change `from mission_control.models import Range` to `from engine.models import Range`
    - `orchestration.py`: Change import
    - `serialization.py`: Change import
☐ Phase 1.4 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_models.py tests/test_range_api.py -v`, confirm all pass

#### Phase 1.FINAL VERIFY

☐ Phase 1.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 1.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

### Phase 2: Move Internal Services to Engine

#### Phase 2.1: Move ECS service

☐ Phase 2.1 PREP: Read tdd-plan.md
☐ Phase 2.1 RED: Write failing tests for ECS service import from engine.services.ecs
    - Test file: `tests/test_engine_services.py`
    - Test: `TestECSService::test_start_provisioning_importable`
    - Test: `TestECSService::test_start_teardown_importable`
    - Test: `TestECSService::test_get_task_status_importable`
☐ Phase 2.1 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestECSService -v`, confirm ImportError
☐ Phase 2.1 GREEN: Move ECS service from mission_control/services/engine.py to engine/services/ecs.py
    - Create `engine/services/ecs.py`
    - Move all functions from mission_control/services/engine.py
    - Update orchestration.py to import from engine.services.ecs
    - Add re-export in mission_control/services/engine.py for backwards compat during migration
☐ Phase 2.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestECSService -v`, confirm pass

#### Phase 2.2: Move SSH service

☐ Phase 2.2 PREP: Read tdd-plan.md
☐ Phase 2.2 RED: Write failing tests for SSH service import from engine.services.ssh
    - Test file: `tests/test_engine_services.py`
    - Test: `TestSSHService::test_ssh_connection_importable`
    - Test: `TestSSHService::test_ssh_connection_error_importable`
☐ Phase 2.2 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestSSHService -v`, confirm ImportError
☐ Phase 2.2 GREEN: Move SSH service from mission_control/services/ssh.py to engine/services/ssh.py
    - Create `engine/services/ssh.py`
    - Move SSHConnection and SSHConnectionError classes
    - Add re-export in mission_control/services/ssh.py for backwards compat during migration
☐ Phase 2.2 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestSSHService -v`, confirm pass

#### Phase 2.3: Move Secrets service

☐ Phase 2.3 PREP: Read tdd-plan.md
☐ Phase 2.3 RED: Write failing tests for Secrets service import from engine.services.secrets
    - Test file: `tests/test_engine_services.py`
    - Test: `TestSecretsService::test_get_ssh_key_importable`
    - Test: `TestSecretsService::test_secrets_error_importable`
☐ Phase 2.3 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestSecretsService -v`, confirm ImportError
☐ Phase 2.3 GREEN: Move Secrets service from mission_control/services/secrets.py to engine/services/secrets.py
    - Create `engine/services/secrets.py`
    - Move get_ssh_key and SecretsError
    - Add re-export in mission_control/services/secrets.py for backwards compat during migration
☐ Phase 2.3 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestSecretsService -v`, confirm pass

#### Phase 2.FINAL VERIFY

☐ Phase 2.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 2.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

### Phase 3: Implement Engine Service Interface

The stub in `engine/services.py` needs to be implemented to match the documented interface.

#### Phase 3.1: Implement get_range_status

☐ Phase 3.1 PREP: Read tdd-plan.md
☐ Phase 3.1 RED: Write failing tests for get_range_status service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestRangeStatusService::test_get_range_status_returns_dict`
    - Test: `TestRangeStatusService::test_get_range_status_not_found`
    - Test: `TestRangeStatusService::test_get_range_status_includes_instances`
☐ Phase 3.1 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestRangeStatusService -v`, confirm NotImplementedError
☐ Phase 3.1 GREEN: Implement get_range_status in engine/services.py
    - Fetch Range by ID
    - Return dict with status, progress, message, instances
    - Use serialization.range_to_dict as base
☐ Phase 3.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestRangeStatusService -v`, confirm pass

#### Phase 3.2: Implement pause_range (DEFERRED)

> **DEFERRED**: Skip this phase for now. Will implement later.

☐ Phase 3.2 PREP: Read tdd-plan.md
☐ Phase 3.2 RED: Write failing tests for pause_range service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestPauseRangeService::test_pause_range_from_ready`
    - Test: `TestPauseRangeService::test_pause_range_not_found`
    - Test: `TestPauseRangeService::test_pause_range_invalid_status`
☐ Phase 3.2 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestPauseRangeService -v`, confirm NotImplementedError
☐ Phase 3.2 GREEN: Implement pause_range in engine/services.py
    - Validate range exists and in READY status
    - Update status to PAUSED
    - Trigger EC2 stop instances (via ECS task or direct)
☐ Phase 3.2 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestPauseRangeService -v`, confirm pass

#### Phase 3.3: Implement resume_range (DEFERRED)

> **DEFERRED**: Skip this phase for now. Will implement later.

☐ Phase 3.3 PREP: Read tdd-plan.md
☐ Phase 3.3 RED: Write failing tests for resume_range service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestResumeRangeService::test_resume_range_from_paused`
    - Test: `TestResumeRangeService::test_resume_range_not_found`
    - Test: `TestResumeRangeService::test_resume_range_invalid_status`
☐ Phase 3.3 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestResumeRangeService -v`, confirm NotImplementedError
☐ Phase 3.3 GREEN: Implement resume_range in engine/services.py
    - Validate range exists and in PAUSED status
    - Update status to RESUMING
    - Trigger EC2 start instances (via ECS task or direct)
☐ Phase 3.3 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestResumeRangeService -v`, confirm pass

#### Phase 3.4: Implement connect_terminal

☐ Phase 3.4 PREP: Read tdd-plan.md
☐ Phase 3.4 RED: Write failing tests for connect_terminal service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestConnectTerminalService::test_connect_terminal_returns_connection`
    - Test: `TestConnectTerminalService::test_connect_terminal_no_range`
    - Test: `TestConnectTerminalService::test_connect_terminal_range_not_ready`
    - Test: `TestConnectTerminalService::test_connect_terminal_invalid_instance_type`
☐ Phase 3.4 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestConnectTerminalService -v`, confirm NotImplementedError
☐ Phase 3.4 GREEN: Implement connect_terminal in engine/services.py
    - Validate user has range in READY status
    - Get instance IP based on instance_type (attacker/victim)
    - Get SSH key from secrets
    - Return SSHConnection instance
☐ Phase 3.4 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestConnectTerminalService -v`, confirm pass

#### Phase 3.5: Wire up create_range to orchestration.launch

☐ Phase 3.5 PREP: Read tdd-plan.md
☐ Phase 3.5 RED: Write failing tests for create_range service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestCreateRangeService::test_create_range_returns_id`
    - Test: `TestCreateRangeService::test_create_range_with_config`
☐ Phase 3.5 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestCreateRangeService -v`, confirm NotImplementedError
☐ Phase 3.5 GREEN: Implement create_range in engine/services.py
    - Parse range_config dict
    - Call orchestration.launch with extracted params
    - Return range.id
☐ Phase 3.5 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestCreateRangeService -v`, confirm pass

#### Phase 3.6: Wire up destroy_range to orchestration.destroy

☐ Phase 3.6 PREP: Read tdd-plan.md
☐ Phase 3.6 RED: Write failing tests for destroy_range service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestDestroyRangeService::test_destroy_range_by_id`
    - Test: `TestDestroyRangeService::test_destroy_range_not_found`
☐ Phase 3.6 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestDestroyRangeService -v`, confirm NotImplementedError
☐ Phase 3.6 GREEN: Implement destroy_range in engine/services.py
    - Get Range by ID
    - Call orchestration logic (or new by-id destroy)
☐ Phase 3.6 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestDestroyRangeService -v`, confirm pass

#### Phase 3.7: Wire up cancel_range

☐ Phase 3.7 PREP: Read tdd-plan.md
☐ Phase 3.7 RED: Write failing tests for cancel_range service
    - Test file: `tests/test_engine_services.py`
    - Test: `TestCancelRangeService::test_cancel_range_by_id`
    - Test: `TestCancelRangeService::test_cancel_range_not_found`
☐ Phase 3.7 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestCancelRangeService -v`, confirm NotImplementedError
☐ Phase 3.7 GREEN: Implement cancel_range in engine/services.py
    - Get Range by ID
    - Call orchestration logic
☐ Phase 3.7 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_services.py::TestCancelRangeService -v`, confirm pass

#### Phase 3.FINAL VERIFY

☐ Phase 3.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 3.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

### Phase 4: Implement NGFW Services

#### Phase 4.1: Create NGFW service module

☐ Phase 4.1 PREP: Read tdd-plan.md
☐ Phase 4.1 RED: Write failing tests for NGFW service functions
    - Test file: `tests/test_engine_ngfw_services.py`
    - Test: `TestNGFWService::test_list_ngfws`
    - Test: `TestNGFWService::test_get_ngfw`
    - Test: `TestNGFWService::test_provision_ngfw`
    - Test: `TestNGFWService::test_start_ngfw`
    - Test: `TestNGFWService::test_stop_ngfw`
    - Test: `TestNGFWService::test_deprovision_ngfw`
☐ Phase 4.1 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_engine_ngfw_services.py -v`, confirm ImportError
☐ Phase 4.1 GREEN: Create engine/services/ngfw.py with service functions
    - list_ngfws(user) -> QuerySet
    - get_ngfw(user, ngfw_id) -> UserNGFW
    - provision_ngfw(user, name, deployment_profile_id, ...) -> UserNGFW
    - start_ngfw(user, ngfw_id) -> UserNGFW
    - stop_ngfw(user, ngfw_id) -> UserNGFW
    - deprovision_ngfw(user, ngfw_id, confirm_name) -> UserNGFW
☐ Phase 4.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_engine_ngfw_services.py -v`, confirm pass

#### Phase 4.FINAL VERIFY

☐ Phase 4.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 4.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

### Phase 5: Refactor Mission Control Views to Use Engine Services

#### Phase 5.1: Refactor NGFW views to use engine services

☐ Phase 5.1 PREP: Read tdd-plan.md
☐ Phase 5.1 RED: Write failing tests verifying MC views use engine services
    - Existing tests should continue to pass
    - No new tests needed - verify existing tests work
☐ Phase 5.1 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_ngfw_views.py -v`, verify they pass before changes
☐ Phase 5.1 GREEN: Refactor mission_control/views.py NGFW functions
    - `api_ngfw_list`: Call `from engine.services.ngfw import list_ngfws`
    - `api_ngfw_provision`: Call `from engine.services.ngfw import provision_ngfw`
    - `api_ngfw_status`: Call `from engine.services.ngfw import get_ngfw`
    - `api_ngfw_start`: Call `from engine.services.ngfw import start_ngfw`
    - `api_ngfw_stop`: Call `from engine.services.ngfw import stop_ngfw`
    - `api_ngfw_deprovision`: Call `from engine.services.ngfw import deprovision_ngfw`
    - Keep view functions thin - just HTTP handling
☐ Phase 5.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_ngfw_views.py -v`, confirm pass

#### Phase 5.2: Refactor terminal view

☐ Phase 5.2 PREP: Read tdd-plan.md
☐ Phase 5.2 RED: Verify terminal view tests exist and pass
☐ Phase 5.2 VERIFY RED: Run `TESTING=1 uv run python -m pytest tests/test_views.py -v -k terminal`, verify status
☐ Phase 5.2 GREEN: Refactor terminal view to use engine services
    - Use `from engine.services import connect_terminal` (when implemented)
    - Or use `from engine.models import Range` for now
☐ Phase 5.2 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/test_views.py -v -k terminal`, confirm pass

#### Phase 5.FINAL VERIFY

☐ Phase 5.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 5.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

### Phase 6: Remove Backwards Compatibility Re-exports

Once all consumers are updated, remove the re-exports from mission_control.

#### Phase 6.1: Update remaining imports to engine

☐ Phase 6.1 PREP: Read tdd-plan.md
☐ Phase 6.1 GREEN: Search and update all remaining imports
    - `grep -r "from mission_control.models import.*Range" --include="*.py"`
    - `grep -r "from mission_control.models import.*UserNGFW" --include="*.py"`
    - `grep -r "from mission_control.services.engine import" --include="*.py"`
    - `grep -r "from mission_control.services.ssh import" --include="*.py"`
    - `grep -r "from mission_control.services.secrets import" --include="*.py"`
    - Update each to import from engine
☐ Phase 6.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm pass

#### Phase 6.2: Remove re-exports from mission_control

☐ Phase 6.2 PREP: Read tdd-plan.md
☐ Phase 6.2 GREEN: Remove backwards compat re-exports
    - Remove Range, UserNGFW re-exports from mission_control/models.py
    - Remove re-exports from mission_control/services/engine.py
    - Remove re-exports from mission_control/services/ssh.py
    - Remove re-exports from mission_control/services/secrets.py
    - Delete empty files if appropriate
☐ Phase 6.2 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm pass

#### Phase 6.3: Update test imports

☐ Phase 6.3 PREP: Read tdd-plan.md
☐ Phase 6.3 GREEN: Update test file imports
    - `tests/test_range_api.py`: Update imports
    - `tests/test_ngfw_models.py`: Update imports
    - `tests/test_ngfw_views.py`: Update imports
    - `tests/test_engine.py`: Update imports
☐ Phase 6.3 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm pass

#### Phase 6.FINAL VERIFY

☐ Phase 6.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 6.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

### Phase 7: Clean Up and Documentation

#### Phase 7.1: Update engine service interface exports

☐ Phase 7.1 PREP: Read tdd-plan.md
☐ Phase 7.1 GREEN: Update engine/services/__init__.py to export public interface
    - Export: create_range, destroy_range, cancel_range, get_range_status, pause_range, resume_range, connect_terminal
    - Keep implementation in submodules, expose clean interface
☐ Phase 7.1 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm pass

#### Phase 7.2: Remove deprecated engine/services.py

☐ Phase 7.2 PREP: Read tdd-plan.md
☐ Phase 7.2 GREEN: Delete engine/services.py (stub file)
    - All functionality now in engine/services/__init__.py or submodules
    - Verify no imports reference engine.services directly (without submodule)
☐ Phase 7.2 VERIFY GREEN: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm pass

#### Phase 7.FINAL VERIFY

☐ Phase 7.FINAL VERIFY: Run `pre-commit run --all-files`, confirm no failures
☐ Phase 7.FINAL VERIFY: Run `TESTING=1 uv run python -m pytest tests/ -v`, confirm no regressions

---

## Summary of Files Changed

### New Files Created
- `engine/models.py` - Range, UserNGFW models
- `engine/services/ecs.py` - ECS Fargate service
- `engine/services/ssh.py` - SSH connection service
- `engine/services/secrets.py` - AWS Secrets Manager service
- `engine/services/ngfw.py` - NGFW lifecycle service
- `tests/test_engine_models.py` - Model tests
- `tests/test_engine_services.py` - Service tests
- `tests/test_engine_ngfw_services.py` - NGFW service tests

### Files Modified
- `engine/services/__init__.py` - Implement public interface
- `engine/services/allocation.py` - Update imports
- `engine/services/orchestration.py` - Update imports
- `engine/services/scenarios.py` - No changes needed (imports cms.models)
- `engine/services/serialization.py` - Update imports
- `mission_control/models.py` - Remove Range, UserNGFW (add temp re-exports, then remove)
- `mission_control/views.py` - Refactor NGFW views to use engine services
- `mission_control/services/engine.py` - Add temp re-export, then delete
- `mission_control/services/ssh.py` - Add temp re-export, then delete
- `mission_control/services/secrets.py` - Add temp re-export, then delete
- `tests/test_range_api.py` - Update imports
- `tests/test_ngfw_models.py` - Update imports
- `tests/test_ngfw_views.py` - Update imports
- `tests/test_engine.py` - Update imports

### Files Deleted
- `engine/services.py` - Replaced by services/__init__.py
- `mission_control/services/engine.py` - Moved to engine (after migration)
- `mission_control/services/ssh.py` - Moved to engine (after migration)
- `mission_control/services/secrets.py` - Moved to engine (after migration)

---

## Dependencies

```
Phase 1 (Models) → Phase 2 (Internal Services) → Phase 3 (Service Interface)
                                                            ↓
Phase 4 (NGFW Services) → Phase 5 (Refactor Views) → Phase 6 (Remove Re-exports)
                                                            ↓
                                                    Phase 7 (Cleanup)
```

---

## Risk Mitigation

1. **Django Migrations**: Moving models between apps requires careful migration handling
   - Use `SeparateDatabaseAndState` operations if needed
   - Test migrations in dev before applying

2. **Import Circular Dependencies**: Monitor for circular imports during model moves
   - Use TYPE_CHECKING imports where needed
   - Keep imports at function level if necessary

3. **Test Coverage**: Existing tests may break during migration
   - Run full test suite after each phase
   - Update test imports immediately when source moves

4. **Backwards Compatibility**: Temporary re-exports ensure gradual migration
   - Remove re-exports only after all consumers updated
   - Phase 6 handles final cleanup
