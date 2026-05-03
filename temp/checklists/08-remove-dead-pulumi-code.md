# Checklist: Remove Dead Pulumi Code from Provisioner

**Priority:** MEDIUM (Reduces main.py by ~500 lines, simplifies decomposition) | **Effort:** Small-Medium (2-4 hours) | **Risk if deferred:** Confusion about which IaC path is active, dead code maintenance burden

---

## Context

The provisioner migrated from Pulumi to Terraform for range provisioning. The entrypoint (`main.py:2899-2901`) exclusively calls `run_range_terraform()`. The old `run_pulumi()` function and its supporting code are never called but remain in the codebase (~500 lines).

**Evidence that Pulumi range code is dead:**
- Entrypoint line 2900: `# Use Terraform for ranges` -> `run_range_terraform(tf_op, request_id)`
- `run_pulumi()` has ZERO callers (confirmed via grep across entire provisioner)
- `has_terraform_state` does NOT appear in the codebase (no runtime switching)
- NGFW provisioning uses Terraform exclusively via `ngfw_terraform.py`

**What IS still alive (Pulumi SDK used by Pulumi program):**
- `stacks/range_stack.py` - `import pulumi`, `pulumi.ComponentResource` - This is the Pulumi **program** that `pulumi up` runs
- `components/network.py` - `import pulumi`, `import pulumi_aws` - Pulumi component resources
- `components/instance.py` - `import pulumi`, `import pulumi_aws` - Pulumi component resources
- `config.py` - `import pulumi`, `pulumi.Config()` - Reads Pulumi stack config

These are the Pulumi **program files** that Pulumi CLI executes. They are only invoked when `pulumi up` runs, which only happens through `run_pulumi()` / `_run_provision()` / `_run_destroy()` - all dead code.

---

## Pre-Work: Verify Pulumi Is Truly Dead

- [ ] Grep entire provisioner for `run_pulumi` calls (not definitions):
    ```
    Expected: only the def line and one comment reference
    ```
- [ ] Grep entire codebase (not just provisioner) for `run_pulumi`:
    ```
    Expected: no callers outside main.py
    ```
- [ ] Grep for `has_terraform_state` anywhere in the codebase:
    ```
    Expected: zero matches (no runtime IaC selection)
    ```
- [ ] Read the entrypoint dispatch (main.py ~2892-2911) and confirm only `run_range_terraform` is called for ranges
- [ ] Check ECS task definitions in Terraform/IaC to confirm the container command uses `range` resource type (not a Pulumi-specific path)
- [ ] Check if any existing ranges in the database were provisioned with Pulumi (would need Pulumi for destroy):
    - [ ] Query: `SELECT id, status FROM mission_control_range WHERE status NOT IN ('destroyed', 'failed')` in dev
    - [ ] If active Pulumi-provisioned ranges exist, they need to be destroyed first OR the Pulumi destroy path needs to remain temporarily
- [ ] Check if `Pulumi.yaml` or `Pulumi.<stack>.yaml` config files exist in the provisioner directory

## Phase 1: Remove Dead Functions from `main.py`

### Pulumi CLI Wrapper Functions (lines 1850-2310)
These are the functions that CALL the `pulumi` CLI binary:

- [ ] Remove `run_pulumi()` (line 1850, ~80 lines) - main Pulumi orchestrator
- [ ] Remove `_select_or_create_stack()` (line 1932, ~55 lines) - stack selection/creation
- [ ] Remove `_set_stack_config()` (line 1990, ~48 lines) - stack config from env vars
- [ ] Remove `_run_provision()` (line 2039, ~170 lines) - Pulumi up + post-provision
- [ ] Remove `_run_destroy()` (line 2209, ~100 lines) - Pulumi destroy + cleanup

### Pulumi Utility Functions
- [ ] Remove `_get_pulumi_path()` (line 179, ~8 lines) - `shutil.which("pulumi")`
- [ ] Remove `_get_working_dir()` (line 188, ~10 lines) - ONLY if it's not used by Terraform paths too
    - [ ] Check: does `_get_working_dir()` appear anywhere except Pulumi functions?
    - [ ] If also used by Terraform, KEEP it
- [ ] Remove `_validate_pulumi_output_schema()` (line 306, ~18 lines) - validates Pulumi output format
    - [ ] Check: is this function called by Terraform paths?
    - [ ] If `_run_terraform_provision` also calls it, it may need to be kept or renamed

### Pulumi-Only Comments and References
- [ ] Update module docstring (line 1-8): Remove "Pulumi stack creation, provisioning, and destruction"
- [ ] Remove `import subprocess` (line 15) - ONLY if no other code uses subprocess
    - [ ] Check: grep main.py for `subprocess` usage outside Pulumi functions
- [ ] Remove `import shutil` (line 14) - ONLY if no other code uses shutil
    - [ ] Check: grep main.py for `shutil` usage outside `_get_pulumi_path()`
- [ ] Remove the section comment `# Post-Pulumi Setup Functions` (line 1222-1223) - rename to reflect Terraform
- [ ] Update the `run_range_terraform` docstring that says "This is the Terraform equivalent of run_pulumi" (line 2316) - it's now the only path
- [ ] Search for and update/remove all remaining "Pulumi" references in comments throughout main.py

## Phase 2: Remove Dead Pulumi Program Files

**These files are only executed by `pulumi up` which is dead code:**

### `stacks/range_stack.py` (867 lines)
- [ ] Verify: no imports of `RangeStack` outside of dead Pulumi paths
    - `stacks/__init__.py` exports it
    - Check: who imports from `stacks`?
- [ ] Verify: `range_stack.py` imports `from main import poll_for_serial_number` - this is a live function used by ngfw_terraform too, so the function stays but this import site goes away
- [ ] Delete `stacks/range_stack.py`

### `stacks/__init__.py`
- [ ] Delete `stacks/__init__.py` (only exports RangeStack)
- [ ] Delete `stacks/` directory entirely (including `__pycache__`)

### `components/network.py` (932 lines) - CAREFUL
- [ ] Check: does `components/network.py` contain ANYTHING used outside Pulumi paths?
    - `allocate_subnets()` function - is this called by Terraform paths?
    - Advisory lock logic - is this used by Terraform?
    - `_get_db_connection()` - this is a duplicate, used only within this file
- [ ] If `allocate_subnets()` IS used by Terraform paths:
    - Extract the non-Pulumi functions to a separate module (e.g., `subnet_allocation.py`)
    - Delete the Pulumi ComponentResource classes
    - Update imports in Terraform path
- [ ] If `allocate_subnets()` is NOT used by Terraform paths:
    - Delete `components/network.py` entirely

### `components/instance.py` (792 lines) - CAREFUL
- [ ] Check: does `components/instance.py` contain ANYTHING used outside Pulumi paths?
    - `sanitize_hostname()` is imported by main.py line 30 - is it used in Terraform paths?
    - `_get_dc_instance_type()` etc. are imported from `catalog/instances.py`, not from here
- [ ] Grep for `from components.instance import` across the codebase
- [ ] If `sanitize_hostname()` IS used by Terraform paths:
    - Move `sanitize_hostname()` to `utils.py`
    - Delete the rest of `components/instance.py`
- [ ] If nothing is used:
    - Delete `components/instance.py` entirely

### `components/__init__.py` and `components/` directory
- [ ] Check if any other files exist in `components/`
- [ ] If only `network.py` and `instance.py` (both deleted), delete the directory

### `config.py` Pulumi Dependencies
- [ ] `config.py` line 21: `import pulumi` - used in `load_config()` which reads `pulumi.Config()`
- [ ] `load_config()` is the Pulumi program's config loader - only called during `pulumi up`
- [ ] Check: is `load_config()` called by anything other than Pulumi programs?
- [ ] Check: is `generate_presigned_url()` or other functions in config.py used by Terraform paths?
    - `from config import generate_presigned_url` in main.py line 31
    - Check if this is used in the Terraform provision path
- [ ] If `load_config()` is Pulumi-only but other functions are shared:
    - Remove `load_config()` and `import pulumi`
    - Keep other functions
- [ ] If the entire file is Pulumi-only:
    - Delete `config.py`

## Phase 3: Remove Dead Test Code

### `tests/test_range_stack.py`
- [ ] Read the file - it only contains `assert RangeStack is not None`
- [ ] Delete `tests/test_range_stack.py`

### `tests/conftest.py` Pulumi Fixtures
- [ ] Read conftest.py and identify Pulumi-specific fixtures (line 184: `import pulumi`)
- [ ] Remove Pulumi mock infrastructure fixtures
- [ ] Keep any fixtures used by non-Pulumi tests

### Component Test Files
- [ ] Check for `tests/test_network_component.py` or similar - delete if they exist
- [ ] Check for `tests/test_instance_component.py` - delete if exists

## Phase 4: Remove Pulumi Dependencies

### Python Package Dependencies
- [ ] Check `requirements.txt` or `pyproject.toml` for Pulumi packages:
    - `pulumi`
    - `pulumi-aws`
    - Any other `pulumi-*` packages
- [ ] Remove Pulumi packages from requirements
- [ ] Run `pip install -r requirements.txt` to verify no other package depends on Pulumi

### Pulumi Configuration Files
- [ ] Check for `Pulumi.yaml` in provisioner directory - delete if exists
- [ ] Check for `Pulumi.*.yaml` stack config files - delete if exists
- [ ] Check for `.pulumi/` state directory - should not exist (state is in S3)

### Infrastructure/Deployment References
- [ ] Check ECS task definition for `PULUMI_CONFIG_PASSPHRASE` env var - can be removed
- [ ] Check ECS task definition for `PULUMI_SECRETS_PROVIDER` env var - can be removed
- [ ] Check if Pulumi state S3 bucket exists - flag for cleanup (separate infrastructure task)
- [ ] Check if KMS key for Pulumi secrets exists - flag for cleanup

## Verification

- [ ] Run full provisioner test suite: `cd provisioner && python -m pytest -v`
- [ ] Verify entrypoint still works: `python main.py --help`
- [ ] Verify range provision still dispatches correctly: trace through `run_range_terraform`
- [ ] Verify NGFW operations unaffected: trace through `run_ngfw_terraform` and `run_ngfw_operation`
- [ ] Grep entire provisioner for `pulumi` (case insensitive):
    ```
    Expected: zero matches in .py files (may remain in __pycache__ until cleared)
    ```
- [ ] Grep for `_run_provision` (the old Pulumi provision function, distinct from `_run_terraform_provision`):
    ```
    Expected: zero matches
    ```
- [ ] Grep for `_run_destroy` (the old Pulumi destroy function, distinct from `_run_terraform_destroy`):
    ```
    Expected: zero matches
    ```
- [ ] Count lines removed from main.py:
    ```
    Expected: ~500 lines of dead Pulumi functions
    ```
- [ ] Count total files deleted:
    ```
    Expected: range_stack.py, stacks/__init__.py, possibly components/*.py, test_range_stack.py
    ```
- [ ] Verify `import subprocess` is removed IF no other code needs it
- [ ] Verify `import shutil` is removed IF no other code needs it

## Line Count Impact Estimate

| Item | Lines Removed |
|------|---------------|
| `run_pulumi()` | ~80 |
| `_select_or_create_stack()` | ~55 |
| `_set_stack_config()` | ~48 |
| `_run_provision()` | ~170 |
| `_run_destroy()` | ~100 |
| `_get_pulumi_path()` | ~8 |
| `_validate_pulumi_output_schema()` | ~18 |
| Comments/docstrings referencing Pulumi | ~20 |
| **Total from main.py** | **~500** |
| `stacks/range_stack.py` | ~867 |
| `stacks/__init__.py` | ~8 |
| Component files (if fully dead) | ~1,700 |
| Test files | ~30+ |
| **Grand total (if all Pulumi code is dead)** | **~3,100** |

## Ordering Note

**Do this checklist BEFORE the main.py decomposition checklist.** Removing ~500 lines of dead code from main.py first makes the decomposition significantly easier:
- Fewer functions to move
- Fewer cross-references to trace
- Smaller resulting modules
- Clearer picture of what's actually alive
