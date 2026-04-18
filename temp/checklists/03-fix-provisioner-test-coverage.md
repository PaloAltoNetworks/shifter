# Checklist: Increase Provisioner `main.py` Test Coverage

**Priority:** CRITICAL | **Effort:** Large (1-2 weeks) | **Risk if deferred:** Critical orchestration code untested

---

## Context

`provisioner/main.py` is 2,911 lines and orchestrates ALL provisioning, destruction, pause/resume, NGFW coordination, and DB state management. Current test coverage is ~5% - only 3 helper functions are tested:
- `parse_serial_number` (line 847)
- `parse_device_certificate_status` (line 941)
- `poll_for_serial_and_cert` (line 962)

The entire provision/destroy flow, DB state management, NGFW coordination, and error recovery paths are untested.

**Existing test file:** `tests/test_main.py` (152 lines, 14 tests - all for the 3 helpers above)

**Key constraint from CLAUDE.md:** Avoid micro-tests with inline mocks (causes OOM at 27GB+). Use fixtures and integration-style tests.

---

## Pre-Work

- [ ] Read `tests/test_main.py` to understand existing test patterns
- [ ] Read `tests/conftest.py` to understand available fixtures (831 lines)
- [ ] Identify which functions are pure logic (testable without mocks) vs which need DB/AWS mocking
- [ ] Read `tests/test_get_range_data.py` as a model for testing DB-dependent functions
- [ ] List all 37 functions in main.py and categorize by testability:
    - **Pure logic** (no external deps): `get_vpc_gateway_ip`, `_validate_pulumi_output_schema`, `_validate_provisioned_outputs`, `DynamicPlan`, `get_agent_presigned_url`, `get_ami_id`
    - **DB-dependent** (need connection mock): `update_range_status`, `write_provisioned_state`, `mark_range_instances_destroyed`, `get_user_ngfw_data`, `get_range_data_by_request_id`, `get_ngfw_data_by_request_id`, `user_has_active_ranges`, `update_instance_state`, `find_stale_routes_by_cidr`, `find_stale_routes_by_db`
    - **Orchestration** (need multiple mocks): `run_range_terraform`, `_run_terraform_provision`, `_run_terraform_destroy`, `run_pulumi`, `_run_provision`, `_run_destroy`, `run_instance_setup`, `_run_single_instance_setup`, `_run_dc_setup`, `configure_ngfw_subnets`, `remove_ngfw_subnets`, `run_ngfw_operation`

## Phase 1: Pure Logic Functions (No Mocks Needed)

### `get_vpc_gateway_ip()` (line 159)
- [ ] Test with standard CIDR (e.g., `10.0.1.0/24` -> `10.0.1.1`)
- [ ] Test with /16 CIDR
- [ ] Test with /28 (smallest useful)
- [ ] Test with invalid CIDR input (expect exception)

### `_validate_pulumi_output_schema()` (line 306)
- [ ] Test with valid complete output
- [ ] Test missing `subnets` key
- [ ] Test `subnets` wrong type (list instead of dict)
- [ ] Test missing `instances` key
- [ ] Test `instances` wrong type (dict instead of list)

### `_validate_provisioned_outputs()` (line 326)
- [ ] Test with valid outputs matching expected subnet names
- [ ] Test with missing subnet in output
- [ ] Test with instance missing required fields
- [ ] Test with empty instances list

### `DynamicPlan` class (line 91)
- [ ] Test construction with steps list
- [ ] Test `get_steps()` returns correct steps
- [ ] Test with empty steps list

### `get_agent_presigned_url()` (line 59)
- [ ] Test with instance config containing agent s3 key
- [ ] Test with missing s3 key (returns None)
- [ ] Test with missing bucket env var

### `get_ami_id()` (line 120)
- [ ] Test each AMI type maps to correct env var
- [ ] Test unknown AMI type raises error
- [ ] Test missing env var raises error

### `_build_range_terraform_variables()` (line 2579)
- [ ] Test with minimal valid range spec
- [ ] Test with NGFW enabled
- [ ] Test with multiple subnets and instances
- [ ] Test with missing required fields

## Phase 2: DB-Dependent Functions (Mock `get_db_connection`)

Create a shared fixture in conftest.py:
- [ ] Create `mock_db_connection` fixture that provides a mock connection with mock cursor
- [ ] Create `mock_cursor_results` helper to set up `fetchone`/`fetchall` return values

### `update_range_status()` (line 275)
- [ ] Test happy path: status update with no kwargs
- [ ] Test with additional kwargs (error_message, paused_at)
- [ ] Test the `NOW()` special case handling
- [ ] Test that SQL is constructed correctly (verify `cur.execute` args)
- [ ] Test that `conn.commit()` is called

### `write_provisioned_state()` (line 381)
- [ ] Test happy path with subnets and instances
- [ ] Test with empty subnets/instances
- [ ] Test that all expected UPDATE statements are executed

### `mark_range_instances_destroyed()` (line 497)
- [ ] Test happy path returns correct (instance_count, subnet_count)
- [ ] Test with no instances/subnets to destroy

### `get_user_ngfw_data()` (line 561)
- [ ] Test returns data when NGFW exists
- [ ] Test returns None when no NGFW
- [ ] Test with multiple NGFWs (should return first active)

### `get_range_data_by_request_id()` (line 770)
- [ ] Test happy path with valid request_id
- [ ] Test with nonexistent request_id (expect exception)
- [ ] Test response dict has all expected keys

### `user_has_active_ranges()` (line 687)
- [ ] Test returns True when active ranges exist
- [ ] Test returns False when no active ranges
- [ ] Test excludes the specified range_id

### `update_instance_state()` (line 1137)
- [ ] Test NGFW instance update to destroyed status
- [ ] Test NGFW instance update to active status
- [ ] Test app record gets updated alongside instance
- [ ] Test with no matching instance (edge case)

## Phase 3: Orchestration Functions (Integration-Style)

These tests mock external services but test the orchestration logic end-to-end.

### Fixture Setup
- [ ] Create `mock_terraform_runner` fixture (mock `range_terraform_runner`)
- [ ] Create `mock_events` fixture (mock `publish_ready`, `publish_failed`, etc.)
- [ ] Create `mock_executors` fixture (mock SSM, SSH, NGFW executors)
- [ ] Create `sample_range_data` fixture with realistic range spec

### `run_range_terraform()` - Happy Path (line 2313)
- [ ] Mock: `get_range_data_by_request_id`, `_run_terraform_provision`, events
- [ ] Test provision operation dispatches to `_run_terraform_provision`
- [ ] Test destroy operation dispatches to `_run_terraform_destroy`
- [ ] Test invalid operation raises ValueError

### `run_range_terraform()` - Failure Path
- [ ] Test provision failure triggers auto-cleanup (`destroy_range` + `cleanup_range_state`)
- [ ] Test `publish_failed` is called with correct args on failure
- [ ] Test exception is re-raised after cleanup
- [ ] Test cleanup failure doesn't mask original error

### `run_range_terraform()` - NGFW Start Logic
- [ ] Test NGFW in "stopped" state triggers `run_ngfw_operation("start", ...)`
- [ ] Test NGFW in "stopping" state waits for stop, then starts
- [ ] Test NGFW in "starting" state with EC2 "stopped" triggers restart
- [ ] Test NGFW in "starting" state with EC2 "running" proceeds without action
- [ ] Test no NGFW data skips NGFW logic entirely

### `_run_terraform_provision()` - Happy Path (line 2399)
- [ ] Mock: terraform_runner.apply_range, DB functions, NGFW config, instance setup, events
- [ ] Test full provision sequence: apply -> validate -> NGFW config -> instance setup -> DB write -> publish
- [ ] Verify call order (NGFW config before instance setup, DB write before publish)

### `_run_terraform_provision()` - NGFW Configuration
- [ ] Test NGFW subnets configured when NGFW data exists
- [ ] Test NGFW config skipped when no NGFW data
- [ ] Test NGFW config skipped when no NGFW subnet CIDR

### `_run_terraform_destroy()` - Happy Path (line 2522)
- [ ] Mock: terraform_runner.destroy_range, cleanup, DB functions, events
- [ ] Test full destroy sequence: NGFW subnet removal -> terraform destroy -> DB update -> publish
- [ ] Verify `mark_range_instances_destroyed` is called

### `_run_terraform_destroy()` - Failure Path
- [ ] Test terraform destroy failure still attempts DB marking if appropriate
- [ ] Test NGFW subnet removal failure doesn't block destroy

### `run_instance_setup()` (line 1754)
- [ ] Test DC instance is set up FIRST (before other instances)
- [ ] Test non-DC instances are set up in parallel (ThreadPoolExecutor)
- [ ] Test partial failure (some instances fail, others succeed)

### `_run_single_instance_setup()` (line 1484)
- [ ] Test Linux instance gets LinuxBootstrapPlan + LinuxXDRAgentInstallPlan
- [ ] Test Windows instance gets BootstrapPlan + XDRAgentInstallPlan
- [ ] Test Kali instance gets appropriate plans
- [ ] Test setup failure returns error info

### `configure_ngfw_subnets()` (line 1384)
- [ ] Test with multiple subnets
- [ ] Test stale route cleanup before new routes
- [ ] Test SSH executor interaction

### `run_ngfw_operation()` (line 2705)
- [ ] Test start operation
- [ ] Test stop operation
- [ ] Test with ec2_instance_id kwarg
- [ ] Test failure publishes NGFW event with error

## Phase 4: Error Recovery Tests

- [ ] Test `_run_terraform_provision` failure at each stage:
    - Terraform apply fails
    - Output validation fails
    - NGFW config fails
    - Instance setup fails (partial)
    - DB write fails
    - Publish fails
- [ ] For each failure point, verify:
    - Correct error message in `publish_failed`
    - No silent swallowing of exceptions
    - Cleanup attempted where appropriate

## Verification

- [ ] Run full provisioner test suite: `cd provisioner && python -m pytest -v`
- [ ] Verify no OOM issues (watch memory during test run)
- [ ] Count new tests vs existing (target: 50+ new tests)
- [ ] Spot-check that tests verify behavior, not mock call counts
