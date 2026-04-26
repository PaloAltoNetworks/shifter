# Checklist: Decompose `cms/services.py` into Domain Modules

**Priority:** HIGH (Maintainability) | **Effort:** Medium (3-5 days) | **Risk if deferred:** Increasing merge conflicts, cognitive load, untestable functions

---

## Context

`cms/services.py` is 3,440 lines with 38 functions (35 public, 3 private). It handles 7 distinct domains in a single file. The file has clear section comments already separating domains.

**Current domain sections (by line range and function count):**

| Domain | Functions | Lines | Public API |
|--------|-----------|-------|------------|
| Agents | 5 | 43-476 | `create_agent`, `delete_agent`, `list_agents`, `get_agent`, `get_allowed_extensions` |
| Credentials | 4 | 481-964 | `create_credential`, `delete_credential`, `list_credentials`, `get_credential` |
| Ranges | 13 | 966-2450 | `list_ranges`, `get_range`, `get_active_range`, `get_range_by_request_id`, `create_range`, `destroy_range`, `cancel_range`, `destroy_range_by_request_id`, `cancel_range_by_request_id`, `pause_range`, `pause_range_by_request_id`, `resume_range`, `resume_range_by_request_id` |
| Uploads | 3 | 2451-2870 | `initiate_upload`, `complete_upload`, `cancel_upload` |
| User Quota | 1 | 2871-2927 | `get_storage_used` |
| Scenarios | 3 | 2928-3069 | `list_scenarios`, `get_scenario`, `validate_scenario_requirements` |
| NGFWs | 4+3 | 3070-3440 | `list_ngfws`, `get_ngfw`, `create_ngfw`, `destroy_ngfw` + 3 private helpers |

**Current callers** (4 production files):
- `mission_control/views.py` - imports NGFW + range functions
- `mission_control/context_processors.py` - imports `get_active_range`, `get_scenario`
- `mission_control/consumers.py` - imports `get_ngfw`
- `cms/__init__.py` - re-exports via lazy `__getattr__`

**Test files** (6 files):
- `test_services_agents.py`, `test_services_range.py`, `test_services_scenarios.py`
- `test_services_storage.py`, `test_services_upload.py`, `test_services.py`
- `integration/cms/test_services_credentials.py`

---

## Pre-Work

- [ ] Read `cms/services.py` imports section (lines 1-40)
- [ ] Read `cms/__init__.py` to understand the lazy export mechanism
- [ ] Read each caller file to catalog exact imports:
    - `mission_control/views.py`
    - `mission_control/context_processors.py`
    - `mission_control/consumers.py`
- [ ] Read each test file's imports to understand what they import and how
- [ ] Identify shared imports that ALL domain modules will need (logger, User type, CMSError)
- [ ] Identify cross-domain dependencies (does `create_range` call agent functions? Does upload call agent functions?)
- [ ] Verify the `shared/constants.py` values used (USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED)

## Plan the Module Structure

Target structure:
```
cms/
  services/
    __init__.py          # Re-exports everything (backward compatible)
    _shared.py           # Shared validation, logger, common imports
    agents.py            # Agent CRUD + get_allowed_extensions
    credentials.py       # Credential CRUD
    ranges.py            # Range CRUD + lifecycle (pause/resume/destroy/cancel)
    uploads.py           # Upload initiation/completion/cancellation
    storage.py           # get_storage_used
    scenarios.py         # Scenario listing/validation
    ngfws.py             # NGFW CRUD + private helpers
```

- [ ] Confirm this structure with the user before implementing
- [ ] Verify no circular dependencies between modules (e.g., uploads -> agents, ranges -> engine)
- [ ] Decide whether `_shared.py` needs the user validation decorator now or if that's a separate task

## Implementation: Create Module Structure

### Step 1: Create the Package
- [ ] Create `cms/services/` directory
- [ ] Move `cms/services.py` to `cms/services/__init__.py` temporarily (keeps everything working)
- [ ] Run tests to verify nothing broke: `TESTING=1 python -m pytest tests/cms/`

### Step 2: Extract `_shared.py`
- [ ] Create `cms/services/_shared.py` with:
    - `import logging`
    - `from cms.exceptions import CMSError`
    - `from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED`
    - `from shared.enums import ResourceStatus`
    - `logger = logging.getLogger(__name__)`
    - The repeated user validation block as a helper function (for now, not a decorator)
- [ ] Do NOT change `__init__.py` yet - just create the shared module

### Step 3: Extract `agents.py`
- [ ] Create `cms/services/agents.py`
- [ ] Move functions: `create_agent`, `delete_agent`, `list_agents`, `get_agent`, `get_allowed_extensions`
- [ ] Add necessary imports from `_shared.py` and Django models
- [ ] In `cms/services/__init__.py`, replace the moved functions with imports:
    ```python
    from cms.services.agents import create_agent, delete_agent, list_agents, get_agent, get_allowed_extensions
    ```
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/test_services_agents.py`

### Step 4: Extract `credentials.py`
- [ ] Create `cms/services/credentials.py`
- [ ] Move functions: `create_credential`, `delete_credential`, `list_credentials`, `get_credential`
- [ ] Add necessary imports
- [ ] Update `__init__.py` with re-exports
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/ -k credential`

### Step 5: Extract `scenarios.py`
- [ ] Create `cms/services/scenarios.py`
- [ ] Move functions: `list_scenarios`, `get_scenario`, `validate_scenario_requirements`
- [ ] Add necessary imports
- [ ] Update `__init__.py` with re-exports
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/test_services_scenarios.py`

### Step 6: Extract `storage.py`
- [ ] Create `cms/services/storage.py`
- [ ] Move function: `get_storage_used`
- [ ] Add necessary imports
- [ ] Update `__init__.py` with re-exports
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/test_services_storage.py`

### Step 7: Extract `uploads.py`
- [ ] Create `cms/services/uploads.py`
- [ ] Move functions: `initiate_upload`, `complete_upload`, `cancel_upload`
- [ ] Check cross-domain dependency: uploads likely references AgentConfig - import from models, not agents.py
- [ ] Add necessary imports
- [ ] Update `__init__.py` with re-exports
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/test_services_upload.py`

### Step 8: Extract `ngfws.py`
- [ ] Create `cms/services/ngfws.py`
- [ ] Move functions: `_app_to_ngfw_context`, `_validate_ngfw_user`, `_validate_app_id`, `list_ngfws`, `get_ngfw`, `create_ngfw`, `destroy_ngfw`
- [ ] Add necessary imports (note: create_ngfw and destroy_ngfw call engine functions)
- [ ] Update `__init__.py` with re-exports
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/ -k ngfw`

### Step 9: Extract `ranges.py`
- [ ] Create `cms/services/ranges.py`
- [ ] Move all 13 range functions
- [ ] This is the largest module - verify all engine imports are correct
- [ ] Check cross-domain: `create_range` may reference agents or scenarios
- [ ] Add necessary imports
- [ ] Update `__init__.py` with re-exports
- [ ] Run tests: `TESTING=1 python -m pytest tests/cms/test_services_range.py tests/cms/test_services.py`

### Step 10: Clean Up `__init__.py`
- [ ] The `__init__.py` should now contain ONLY imports and `__all__`
- [ ] Verify `__all__` list matches the current `cms/__init__.py` exports
- [ ] Verify the lazy `__getattr__` in `cms/__init__.py` still works with the new package structure
- [ ] Remove all function definitions from `__init__.py` (they should all be in domain modules now)

## Update Callers

- [ ] Check `mission_control/views.py` - imports should still work via `cms/services/__init__.py`
- [ ] Check `mission_control/context_processors.py` - same
- [ ] Check `mission_control/consumers.py` - same
- [ ] If any caller imports `from cms.services import X`, it should still work because `__init__.py` re-exports

## Update Test Imports

- [ ] Check each test file - if they import `from cms import services` and use `services.function_name`, no changes needed
- [ ] If any test patches `cms.services.SomeModel`, update the patch path to `cms.services.agents.SomeModel` (or wherever the model is now imported)
- [ ] This is the most likely breakage point - patch paths must match the actual import location

## Verification

- [ ] Run the FULL platform test suite: `TESTING=1 python -m pytest`
- [ ] Verify each new module can be imported independently:
    ```python
    from cms.services.agents import create_agent
    from cms.services.credentials import create_credential
    # etc.
    ```
- [ ] Verify backward-compatible imports still work:
    ```python
    from cms.services import create_agent  # via __init__.py re-export
    from cms import create_agent  # via cms/__init__.py lazy loading
    ```
- [ ] Verify no circular imports by starting the Django shell: `python manage.py shell`
- [ ] Check that `__init__.py` is under 50 lines (just imports and __all__)
- [ ] Check that no domain module exceeds 600 lines
- [ ] Check that no function was accidentally lost during extraction

## What NOT to Do in This PR

- [ ] Do NOT refactor function internals (e.g., removing duplicate validation)
- [ ] Do NOT add `transaction.atomic()` (separate checklist)
- [ ] Do NOT change the public API surface
- [ ] Do NOT rename functions
- [ ] Do NOT change test assertions - only change import paths if needed
- [ ] This is a PURE structural refactor - zero behavior change
