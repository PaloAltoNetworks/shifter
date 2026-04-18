# Checklist: Decompose `provisioner/main.py` into Focused Modules

**Priority:** HIGH (Maintainability) | **Effort:** Large (1-2 weeks) | **Risk if deferred:** Growing god object, untestable, merge conflicts

---

## Context

`provisioner/main.py` is 2,911 lines with 37 functions and 1 class. It serves as:
1. Container entrypoint (CLI argument parsing)
2. Database access layer (get_db_connection, all raw SQL)
3. Pulumi orchestration (run_pulumi, _run_provision, _run_destroy) - DEAD CODE
4. Terraform orchestration (run_range_terraform, _run_terraform_provision, _run_terraform_destroy)
5. Instance setup orchestration (run_instance_setup, _run_single_instance_setup, _run_dc_setup)
6. NGFW management (configure_ngfw_subnets, remove_ngfw_subnets, run_ngfw_operation)
7. Utility functions (parse_serial_number, get_ami_id, get_vpc_gateway_ip)
8. Validation functions (_validate_pulumi_output_schema, _validate_provisioned_outputs)

**Other files that import from main.py:**
- `range_ops.py` - imports `get_db_connection`, `get_range_data_by_request_id`, `update_range_status`
- `ngfw_terraform.py` - imports `poll_for_serial_number`, `poll_for_serial_and_cert`, `get_ngfw_data_by_request_id`, `update_instance_state`, `run_ngfw_operation`
- `stacks/range_stack.py` - imports `poll_for_serial_number`
- `config.py` - has its own duplicate `get_db_connection()`
- `components/network.py` - has its own duplicate `_get_db_connection()`

---

## Pre-Work

- [ ] Read `main.py` fully to understand all function boundaries
- [ ] Map every import from other files into main.py (listed above)
- [ ] Map every cross-function call within main.py (which functions call which)
- [ ] Identify which functions are only used by Pulumi paths (candidates for removal - see separate checklist)
- [ ] Identify natural module boundaries based on function clustering:
    - DB access functions cluster together
    - Terraform functions call each other
    - Instance setup functions call each other
    - NGFW functions call each other

## Plan the Module Structure

Target structure:
```
provisioner/
  main.py                  # ONLY entrypoint (argparse + dispatch) - target <100 lines
  db.py                    # Database connection + all raw SQL operations
  range_provision.py       # run_range_terraform, _run_terraform_provision, _run_terraform_destroy
  range_destroy.py         # OR keep provision+destroy together in range_provision.py
  instance_setup.py        # run_instance_setup, _run_single_instance_setup, _run_dc_setup, DynamicPlan
  ngfw_ops.py              # configure_ngfw_subnets, remove_ngfw_subnets, run_ngfw_operation, find_stale_routes_*
  ngfw_polling.py          # parse_serial_number, poll_for_serial_number, parse_device_certificate_status, poll_for_serial_and_cert, wait_for_autocommit
  validation.py            # _validate_pulumi_output_schema, _validate_provisioned_outputs
  utils.py                 # get_ami_id, get_vpc_gateway_ip, get_agent_presigned_url
```

- [ ] Confirm this structure with the user before implementing
- [ ] Verify no circular dependencies in the planned structure
- [ ] Decide: should `_build_range_terraform_variables()` go in `range_provision.py` or `utils.py`?

## Implementation: Extract Bottom-Up (Least Dependencies First)

### Step 1: Extract `utils.py` (Zero Internal Dependencies)
- [ ] Create `provisioner/utils.py`
- [ ] Move: `get_ami_id`, `get_vpc_gateway_ip`, `get_agent_presigned_url`
- [ ] These functions have NO dependencies on other main.py functions
- [ ] Update imports in main.py: `from utils import get_ami_id, get_vpc_gateway_ip, get_agent_presigned_url`
- [ ] Search for callers of these functions in other files and update imports
- [ ] Run tests: `python -m pytest`

### Step 2: Extract `db.py` (Foundation Layer)
- [ ] Create `provisioner/db.py`
- [ ] Move `get_db_connection()` function
- [ ] Move ALL raw SQL functions:
    - `update_range_status`
    - `write_provisioned_state`
    - `mark_range_instances_destroyed`
    - `get_user_ngfw_data`
    - `get_range_data_by_request_id`
    - `get_ngfw_data_by_request_id`
    - `user_has_active_ranges`
    - `update_instance_state`
    - `find_stale_routes_by_cidr`
    - `find_stale_routes_by_db`
- [ ] Move imports: `psycopg`, `from psycopg import sql`, `boto3` (for RDS IAM), `json`
- [ ] Update main.py to import from db.py
- [ ] Update `range_ops.py` imports: change `from main import get_db_connection, ...` to `from db import ...`
- [ ] Update `ngfw_terraform.py` imports: change `from main import get_ngfw_data_by_request_id, update_instance_state` to `from db import ...`
- [ ] **Remove duplicate** `get_db_connection()` from `config.py` - import from `db.py` instead
- [ ] **Remove duplicate** `_get_db_connection()` from `components/network.py` - import from `db.py` instead
- [ ] Run tests: `python -m pytest`

### Step 3: Extract `validation.py`
- [ ] Create `provisioner/validation.py`
- [ ] Move: `_validate_pulumi_output_schema`, `_validate_provisioned_outputs`
- [ ] Note: `_validate_pulumi_output_schema` may be removable if Pulumi code is being deleted (see separate checklist). If so, skip it.
- [ ] Move or rename: `_validate_provisioned_outputs` -> `validate_provisioned_outputs` (make it public since it's now in its own module)
- [ ] Update imports in main.py
- [ ] Run tests: `python -m pytest`

### Step 4: Extract `ngfw_polling.py` (NGFW Serial/Cert Polling)
- [ ] Create `provisioner/ngfw_polling.py`
- [ ] Move: `parse_serial_number`, `poll_for_serial_number`, `parse_device_certificate_status`, `poll_for_serial_and_cert`, `wait_for_autocommit`
- [ ] These are called by `ngfw_terraform.py` and `stacks/range_stack.py`
- [ ] Update imports in:
    - `main.py`
    - `ngfw_terraform.py`: change `from main import poll_for_serial_number` to `from ngfw_polling import poll_for_serial_number`
    - `ngfw_terraform.py`: change `from main import poll_for_serial_and_cert` to `from ngfw_polling import poll_for_serial_and_cert`
    - `stacks/range_stack.py`: change `from main import poll_for_serial_number` to `from ngfw_polling import poll_for_serial_number`
- [ ] Run tests: `python -m pytest tests/test_main.py` (these test the parse functions)

### Step 5: Extract `ngfw_ops.py` (NGFW Subnet/Route Operations)
- [ ] Create `provisioner/ngfw_ops.py`
- [ ] Move: `configure_ngfw_subnets`, `remove_ngfw_subnets`, `run_ngfw_operation`
- [ ] These depend on `db.py` functions and executors
- [ ] Update imports: `from db import get_user_ngfw_data, update_instance_state, find_stale_routes_by_cidr, find_stale_routes_by_db`
- [ ] Update `ngfw_terraform.py`: change `from main import run_ngfw_operation` to `from ngfw_ops import run_ngfw_operation`
- [ ] Run tests: `python -m pytest`

### Step 6: Extract `instance_setup.py`
- [ ] Create `provisioner/instance_setup.py`
- [ ] Move: `DynamicPlan` class, `run_instance_setup`, `_run_single_instance_setup`, `_run_dc_setup`
- [ ] These depend on executors, plans, and orchestrators (already separate modules)
- [ ] Move plan imports with them (BootstrapPlan, DCSetupPlan, etc.)
- [ ] Update imports in main.py
- [ ] Run tests: `python -m pytest`

### Step 7: Extract `range_provision.py`
- [ ] Create `provisioner/range_provision.py`
- [ ] Move: `run_range_terraform`, `_run_terraform_provision`, `_run_terraform_destroy`, `_build_range_terraform_variables`
- [ ] These depend on: `db.py`, `instance_setup.py`, `ngfw_ops.py`, `validation.py`, `range_terraform_runner`, `events`
- [ ] Update imports
- [ ] Run tests: `python -m pytest`

### Step 8: Slim Down `main.py` to Entrypoint Only
- [ ] main.py should now contain ONLY:
    - Module docstring
    - Imports from the new modules
    - `if __name__ == "__main__":` block with argparse
    - Dispatch logic (the `if args.resource == "ngfw"` / `elif args.resource == "range"` block)
- [ ] Target: under 100 lines
- [ ] Verify: `python main.py --help` still works
- [ ] Verify: `python main.py range provision --request-id <uuid>` dispatches correctly

## Update All External References

- [ ] `range_ops.py` - update ALL `from main import X` to `from <new_module> import X`
- [ ] `ngfw_terraform.py` - update ALL `from main import X` (6 import sites, all deferred/inline imports)
- [ ] `stacks/range_stack.py` - update `from main import poll_for_serial_number`
- [ ] `tests/test_main.py` - update `from main import parse_serial_number` etc.
- [ ] `tests/test_get_range_data.py` - update `from main import get_range_data_by_request_id`
- [ ] Search for any remaining `from main import` or `import main` across the provisioner

## Verification

- [ ] Run full provisioner test suite: `cd provisioner && python -m pytest -v`
- [ ] Verify entrypoint still works: `python main.py --help`
- [ ] Verify no circular imports: `python -c "import main"` (no errors)
- [ ] Verify no file exceeds 600 lines
- [ ] Verify main.py is under 100 lines
- [ ] Count functions per module - no module should have more than 12 functions
- [ ] Search for any remaining `from main import` that references a moved function
- [ ] Search for any `mock.patch("main.function_name")` in tests and update patch paths

## What NOT to Do in This PR

- [ ] Do NOT refactor function internals
- [ ] Do NOT fix the SQL injection (separate checklist)
- [ ] Do NOT remove Pulumi code (separate checklist - but can be done first to reduce scope)
- [ ] Do NOT change the CLI interface
- [ ] Do NOT change function signatures
- [ ] This is a PURE structural refactor - zero behavior change
