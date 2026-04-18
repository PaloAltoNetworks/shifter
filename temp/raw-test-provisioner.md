# Shifter Testing Quality Review: Provisioner & Frontend

**Reviewer**: Staff Software Engineer
**Date**: 2026-02-07
**Scope**: Provisioner test suite (43 files, ~7,142 lines), Frontend JS tests (6 files, ~2,923 lines), CyberScript tests (6 files)

---

## Executive Summary

The Shifter test suite demonstrates **thoughtful TDD practices** with clear architectural patterns, but has **significant coverage gaps** given the 2,911-line `main.py` and complex orchestration logic. Tests focus heavily on **structural verification** (does the plan have the right steps?) rather than **behavioral testing** (what happens when AWS fails?). The test quality is inconsistent - executor tests are excellent, but plan tests are too shallow.

**Overall Grade**: C+ (Good intent, meaningful gaps)

---

## 1. Test Configuration & Infrastructure

### 1.1 Conftest Quality (831 lines)

**Strengths:**
- **Excellent Pulumi mocking infrastructure** - `PulumiMocks` class properly implements mock interface with resource tracking
- **Comprehensive fixtures** for database, boto3, subprocess, templates
- **Auto-use fixtures** prevent CI failures (`mock_pulumi_executable`)
- **Good separation** of concerns (Pulumi vs DB vs AWS vs templates)
- **Sample data fixtures** cover single-subnet, multi-subnet, NGFW, and DC scenarios

**Weaknesses:**
- **831 lines is excessive** for conftest - suggests tests are too mock-dependent
- **No fixture for simulating AWS failures** (throttling, timeouts, partial failures)
- **Template fixtures use temporary files** - could use in-memory strings
- **Mock DB cursors are overly verbose** (lines 203-213) - DRY violation across test files

**Risk**: Tests may be brittle if infrastructure changes. No shared failure simulation patterns.

---

## 2. Coverage Analysis

### 2.1 Main.py Coverage (2,911 lines)

**What's Tested:**
- `parse_serial_number()` helper function (7 test cases)
- `parse_device_certificate_status()` helper function (4 test cases)
- `poll_for_serial_and_cert()` polling logic (3 test cases)

**What's NOT Tested (Critical Gaps):**
- ❌ **Main provisioning orchestration flow** (setup vs ops dispatch)
- ❌ **Error handling in main()** - what happens when Pulumi fails?
- ❌ **Database state transitions** - how are status updates written?
- ❌ **NGFW provisioning flow** - coordination between AWS, SSH, and DB writes
- ❌ **Terraform runner integration** - no tests for Terraform execution
- ❌ **Partial failure recovery** - what if instance 3 of 5 fails?
- ❌ **Resource cleanup on failure** - does Pulumi `destroy` run?

**Coverage Estimate**: ~5-10% of main.py logic actually tested

**Critical Missing**: The entire "orchestration of orchestrators" pattern is untested. No integration tests that simulate a full provisioning lifecycle.

---

### 2.2 Executor Test Quality

**Excellent Coverage:**

**SSMExecutor (605 lines of tests):**
- ✅ Happy path, timeouts, retries, reboot logic
- ✅ Polling behavior with `time.sleep` mocking
- ✅ Agent readiness verification with IPC failures
- ✅ Document type support (PowerShell vs Shell)
- ✅ Instance state transitions (stopping → running → ready)

**AWSExecutor (271 lines of tests):**
- ✅ Client caching behavior
- ✅ Error handling (ClientError, WaiterError)
- ✅ Endpoint polling logic with terminal states
- ✅ Action dispatcher validation (missing params, unknown actions)

**NGFWExecutor (182 lines of tests):**
- ✅ SSH key file creation/permissions/cleanup
- ✅ Command input construction (script + stdin)
- ✅ System info readiness checks
- ✅ Context manager protocol

**Assessment**: Executor tests are **production-quality**. They test actual logic, not just mock calls. Good balance of happy path, error cases, and edge cases.

---

### 2.3 Orchestrator Test Quality

**SetupOrchestrator (376 lines of tests):**
- ✅ Step sequencing, reboot handling, verification
- ✅ Error propagation (failures stop execution)
- ✅ Jinja2 template rendering with context
- ✅ Empty plan edge case

**OpsOrchestrator (168 lines of tests):**
- ✅ AWS action execution via AWSExecutor
- ✅ Failure handling (stops on first failure)
- ✅ Integration with real NGFW plans (start/stop)

**Assessment**: Orchestrator tests are **solid** but focus on sequencing logic. Missing: complex failure scenarios, timeouts during multi-step operations, context variable edge cases.

---

### 2.4 Plan Test Quality (18 plan test files)

**Pattern Observed**: Plan tests are **shallow structural tests**:

```python
def test_steps_in_correct_order(self):
    plan = BootstrapPlan()
    step_names = [s.name for s in plan.steps]
    assert step_names == ["set_hostname", "configure_ssh"]
```

**Strengths:**
- ✅ Verify step order and dependencies
- ✅ Check `requires_reboot` flags
- ✅ Validate context extraction (`get_context`)
- ✅ Ensure commits are present in config steps
- ✅ Check poll_for_job flags on NGFW content downloads

**Weaknesses:**
- ❌ **No actual script execution** - just verifies scripts exist
- ❌ **No script correctness testing** - PowerShell/Bash could be syntactically invalid
- ❌ **No rendering validation** - templates could have undefined variables
- ❌ **No timeout tuning validation** - are timeouts realistic?
- ❌ **No failure simulation** - what if AD install fails midway?

**Example Gap**: `NGFWProvisionPlan` has 8 steps configuring firewall. Tests verify:
- "Does step 3 include 'delete rulebase security rules allow-all'?" ✅
- But NOT: "Does this script actually delete the rule?" ❌
- But NOT: "What happens if commit fails?" ❌

**Assessment**: Plan tests are **regressions guards** (detect structural changes) but NOT **behavioral tests** (verify correctness).

---

### 2.5 Component & Stack Tests

**RangeStack (30 lines of tests):**
```python
def test_stack_can_be_imported(self):
    from stacks.range_stack import RangeStack
    assert RangeStack is not None
```

**Assessment**: **Placeholder tests**. No actual infrastructure creation testing. Missing:
- ❌ Pulumi resource creation
- ❌ VPC/subnet allocation logic
- ❌ Route table associations
- ❌ Security group configurations
- ❌ Instance creation with correct AMIs

**NetworkComponent / InstanceComponent**: Not found in test files reviewed.

**Critical Gap**: The core infrastructure-as-code logic is **essentially untested**.

---

### 2.6 Edge Case Tests

**test_edge_cases.py (139 lines):**
- ✅ Many instances per subnet (11 instances)
- ✅ Mixed OS types (ubuntu, windows, amazon-linux)
- ✅ Empty subnets
- ✅ Optional field defaults

**Assessment**: Good boundary testing for config parsing. Missing:
- ❌ Subnet CIDR exhaustion
- ❌ Availability zone failures
- ❌ AMI not found errors
- ❌ Security group conflicts
- ❌ Instance profile permissions failures

---

### 2.7 Integration Tests

**test_setup_integration.py (168 lines):**
- ✅ Error propagation through executor → orchestrator
- ✅ DCSetupPlan with prebaked AMI (password + SSH + verify)
- ✅ Verification failure reporting

**Assessment**: **Best integration test file**. Shows errors bubble up correctly. But still limited:
- ❌ No full provisioning lifecycle test (Pulumi → SSM → DB update)
- ❌ No multi-instance coordination tests
- ❌ No NGFW + range integration test
- ❌ No domain join integration test (DC + member Windows)

---

## 3. Frontend JavaScript Tests

### 3.1 Coverage (6 test files, ~2,923 lines)

**Files:**
- `dashboard.test.js` (~206 lines)
- `terminal.test.js` (~100+ lines, partial view)
- `sidebar.test.js`
- `ngfw.test.js`
- `upload.test.js`
- `xdr-dropdown.test.js`

**Dashboard Tests:**
- ✅ `destroyRange()` sends correct request_id
- ✅ Confirmation dialog handling
- ✅ XdrDropdown initialization
- ✅ Status polling (start/stop, interval timing, stable state detection)
- ✅ WebSocket cleanup

**Terminal Tests (partial view):**
- ✅ Mock WebSocket setup
- ✅ Mock xterm.js Terminal
- ✅ Multi-pane layout (tabs vs split)
- ✅ Connection URL handling

**Assessment**: Frontend tests appear **well-structured** with proper mocking of external dependencies (fetch, WebSocket, xterm.js). Good coverage of state management and user interactions.

**Unknown**: Error handling, reconnection logic, edge cases (slow network, WebSocket failures).

---

## 4. CyberScript Tests

### 4.1 Coverage (6 files)

**Files:**
- `test_events.py` (~219 lines) - Pydantic event models
- `test_channels.py`
- `test_enums.py`
- `test_schemas.py`

**test_events.py Quality:**
- ✅ Event construction with required fields
- ✅ Auto-generated UUIDs and timestamps
- ✅ Serialization (model_dump, model_dump_json)
- ✅ Deserialization (model_validate)
- ✅ Optional fields (error_message, correlation_id)
- ✅ Event type constants

**Assessment**: **Excellent unit tests** for Pydantic models. Comprehensive coverage of serialization, validation, and edge cases. CyberScript tests are **production-quality**.

---

## 5. Test Patterns & Hygiene

### 5.1 Strengths

✅ **TDD docstrings**: Tests have clear descriptions of intent
✅ **Minimal mocking in executors**: Tests actual logic, not mock calls
✅ **Fixture-based mocks** (not inline): Reduces duplication
✅ **Explicit test class grouping**: Easy to navigate
✅ **pytest-friendly**: Uses pytest idioms (fixtures, parametrize potential)
✅ **No micro-tests with inline mocks**: Avoided OOM anti-pattern

### 5.2 Weaknesses

❌ **No shared failure simulation library**: Each test recreates ClientError mocks
❌ **Heavy reliance on conftest**: 831 lines suggests over-mocking
❌ **Structural tests dominate**: Plans test "does script exist" not "is script correct"
❌ **Missing timeout tests**: No tests for 10-minute AD setup timeout, 30-minute NGFW provisioning
❌ **No property-based testing**: Could use `hypothesis` for config fuzzing
❌ **No concurrency tests**: Multiple instances provision in parallel - not tested

---

## 6. Critical Gaps

### 6.1 Missing Test Categories

#### A. Infrastructure Failures
- ❌ AWS API throttling during provisioning
- ❌ EC2 instance launch failures (capacity, quota)
- ❌ Subnet CIDR exhaustion
- ❌ Security group rule limit exceeded
- ❌ IAM permissions failures (instance profile)

#### B. Timing & Concurrency
- ❌ SSM agent install timeout (never comes online)
- ❌ AD DS promotion timeout (30+ minutes)
- ❌ NGFW content download timeout
- ❌ Parallel instance provisioning (5 instances at once)
- ❌ Race conditions in DB status updates

#### C. Partial Failures
- ❌ 3 of 5 instances provision successfully - what happens?
- ❌ DC provisions but verification fails - is it destroyed?
- ❌ NGFW SSH available but serial number never appears
- ❌ Domain join fails on 1 of 3 member servers

#### D. State Management
- ❌ Database transaction failures mid-provisioning
- ❌ Status transitions (pending → provisioning → ready → failed)
- ❌ Idempotency (can same range be provisioned twice?)
- ❌ Cleanup after failure (orphaned AWS resources)

#### E. End-to-End Flows
- ❌ Full basic scenario provision (attacker + victim + agent)
- ❌ Full DC scenario (DC + member Windows + domain join)
- ❌ Full NGFW scenario (NGFW provision + subnet config + rules)
- ❌ Range pause/resume lifecycle
- ❌ Range destroy with cleanup verification

---

## 7. Mock Hygiene Assessment

### 7.1 Good Practices

✅ **Executor tests use real logic**: SSMExecutor polling actually calls `time.sleep` (mocked)
✅ **Command results are dataclasses**: Not raw dicts
✅ **Clear mock boundaries**: AWS SDK mocked, business logic tested

### 7.2 Concerning Patterns

⚠️ **Overly specific mocks**: Tests know exact boto3 call signatures
⚠️ **Implementation coupling**: Mock `send_command` return value structure
⚠️ **No failure rate simulation**: Real AWS has intermittent failures

---

## 8. Assertion Quality

### 8.1 Strong Assertions

✅ **Specific error message checks**: `assert "hostname" in str(exc_info.value)`
✅ **Exit code validation**: `assert result.exit_code == 1`
✅ **State transition verification**: `assert dashboard.currentRange.status == 'ready'`
✅ **Collection length checks**: `assert len(result.step_results) == 2`

### 8.2 Weak Assertions

⚠️ **Existence checks**: `assert RangeStack is not None` (placeholder test)
⚠️ **Mock call counts**: `assert mock.call_count == 3` (brittle, implementation detail)
⚠️ **String contains**: `assert "commit" in script.lower()` (could match comment)

---

## 9. Test Organization

### 9.1 File Structure

```
tests/
├── conftest.py                    # 831 lines - TOO LARGE
├── test_main.py                   # 152 lines - INCOMPLETE (missing 95% of main.py)
├── test_config.py                 # 557 lines - GOOD
├── test_events.py                 # 357 lines - EXCELLENT
├── test_*_executor.py             # 1000+ lines - EXCELLENT
├── test_*_orchestrator.py         # 544 lines - GOOD
├── test_*_plan.py (18 files)      # ~2500 lines - SHALLOW
├── test_*_component.py            # ~30 lines - PLACEHOLDER
├── test_edge_cases.py             # 139 lines - GOOD
├── test_setup_integration.py      # 168 lines - GOOD but LIMITED
```

**Assessment**: Well-organized by component. Clear naming. Missing: dedicated failure scenarios directory.

---

## 10. Recommendations

### 10.1 Immediate Priorities (Sprint 1)

1. **Add main.py integration tests**
   - Test full provision flow (mock Pulumi, real orchestration logic)
   - Test error handling (Pulumi failure, DB write failure)
   - Test status transitions in database

2. **Add infrastructure failure simulation**
   - Create `conftest` fixtures for common failures:
     - `mock_aws_throttle_error`
     - `mock_instance_launch_failure`
     - `mock_ssm_agent_timeout`
   - Write tests using these fixtures

3. **Enhance plan tests with execution**
   - Don't just check scripts exist - render and validate syntax
   - Test Jinja2 edge cases (undefined vars, escaping)
   - Simulate step failures mid-plan

### 10.2 Medium-term Improvements (Sprint 2-3)

4. **Add concurrency tests**
   - Test parallel instance provisioning (5 instances at once)
   - Test race conditions in status updates
   - Test DB transaction isolation

5. **Add E2E tests (smoke tests)**
   - One test per scenario in catalog (basic, dc, ngfw)
   - Mock AWS but use real orchestration + DB writes
   - Verify final DB state matches expected

6. **Refactor conftest.py**
   - Split into `conftest_aws.py`, `conftest_db.py`, `conftest_templates.py`
   - Create failure simulation library in `tests/fixtures/failures.py`

### 10.3 Long-term Quality (Sprint 4+)

7. **Add property-based testing**
   - Use `hypothesis` to fuzz config inputs
   - Test subnet CIDR allocation edge cases
   - Test instance name generation uniqueness

8. **Add mutation testing**
   - Use `mutmut` to verify tests actually catch bugs
   - Target: 80%+ mutation score on critical paths

9. **Add contract tests**
   - Verify Pulumi resource schemas match AWS
   - Verify SSM command documents match AWS versions
   - Verify NGFW PAN-OS commands match version 11.x

---

## 11. Specific Test Gaps by Component

### 11.1 Main.py (2,911 lines)

**Current Coverage**: ~150 lines of tests (5%)
**Missing**:
- Provisioning orchestration flow
- Ops orchestration flow (pause/resume)
- Error handling and recovery
- Database state management
- Pulumi stack lifecycle
- NGFW coordination logic

### 11.2 Plans (18 files)

**Current Coverage**: Structural only
**Missing**:
- Script syntax validation
- Rendering with edge case contexts
- Mid-step failure simulation
- Timeout behavior
- Idempotency (can steps be re-run?)

### 11.3 Components (Network, Instance, Stack)

**Current Coverage**: ~0% (placeholder tests only)
**Missing**:
- Pulumi resource creation
- CIDR allocation logic
- Route table configuration
- Security group rules
- ENI attachment logic

### 11.4 Terraform Runner

**Current Coverage**: ~30 lines
**Missing**:
- Terraform execution
- State file management
- Error handling
- Output parsing
- Resource cleanup

---

## 12. Test Metrics

### 12.1 Quantitative

| Metric | Value | Assessment |
|--------|-------|------------|
| Total test files (provisioner) | 43 | Good |
| Total test lines (provisioner) | 7,142 | Good |
| Total test classes | 146 | Excellent |
| Total test functions | 480 | Excellent |
| Conftest size | 831 lines | ⚠️ Too large |
| main.py coverage | ~5% | ❌ Critical gap |
| Plan test depth | Structural only | ⚠️ Shallow |
| Integration tests | 1 file (168 lines) | ⚠️ Minimal |
| Frontend test files | 6 | Good |
| Frontend test lines | 2,923 | Good |
| CyberScript test files | 6 | Good |

### 12.2 Qualitative

| Category | Grade | Notes |
|----------|-------|-------|
| Executor tests | A | Excellent logic testing |
| Orchestrator tests | B+ | Good sequencing, missing edge cases |
| Plan tests | C | Structural only, not behavioral |
| Component tests | F | Placeholder only |
| Integration tests | C | One file, limited scenarios |
| Edge case tests | B | Good config edges, missing infra edges |
| Frontend tests | B+ | Well-structured, unknown coverage |
| CyberScript tests | A | Comprehensive Pydantic testing |

---

## 13. Anti-Patterns Observed

### 13.1 Avoided (Good!)

✅ **No micro-tests with inline mocks** (lesson learned from OOM issues)
✅ **No testing mock calls** (tests verify logic, not that mocks were called)
✅ **No overly-granular test classes** (well-grouped by behavior)

### 13.2 Present (Needs Attention)

⚠️ **Placeholder tests** (`assert X is not None`) - should be removed or implemented
⚠️ **Mock call count assertions** - brittle, tests implementation not behavior
⚠️ **Structural plan tests** - verify structure, not correctness
⚠️ **Over-reliance on conftest** - 831 lines suggests tests need too much scaffolding

---

## 14. Comparison to Industry Standards

### 14.1 vs. FAANG Infrastructure Code

**Typical FAANG infrastructure repo:**
- 60-80% line coverage
- Dedicated failure injection framework
- Contract tests for external APIs
- E2E tests in staging environment
- Mutation testing on critical paths

**Shifter:**
- ~10-15% estimated coverage (main.py at 5%, other components better)
- No failure injection framework
- No contract tests
- No E2E tests
- No mutation testing

**Gap**: Shifter is **2-3 maturity levels behind** FAANG infrastructure standards.

### 14.2 vs. Open Source IaC Projects (Terraform, Pulumi)

**Typical OSS IaC project:**
- Provider contract tests
- Integration tests against real cloud APIs
- Extensive state management tests
- Upgrade/migration tests

**Shifter:**
- No provider contract tests
- No real cloud integration tests (all mocked)
- Minimal state management tests
- No upgrade tests

**Gap**: Shifter is **adequate for early-stage startup**, but needs investment for enterprise reliability.

---

## 15. Risk Assessment

### 15.1 High-Risk Areas (Untested)

🔴 **Critical:**
- Main provisioning flow (could fail silently)
- Database state transitions (could corrupt state)
- Partial failure handling (could orphan resources)
- NGFW provision coordination (complex SSH + AWS + DB)

🟡 **Medium:**
- Plan script correctness (syntax errors in production)
- Timeout tuning (could hang indefinitely)
- Concurrent provisioning (race conditions)

🟢 **Low:**
- Config parsing (well-tested)
- Executor logic (well-tested)
- Event serialization (well-tested)

### 15.2 Production Readiness

**Can this code ship to production?**

✅ **Yes, for MVP / early customers** (executors are solid, core logic seems sound)
⚠️ **Not for enterprise scale** (untested failure modes, no recovery tests)
❌ **Not for multi-tenant at scale** (no concurrency tests, race condition risks)

---

## 16. Actionable Next Steps

### Week 1: Fill Critical Gaps
1. Write 3 main.py integration tests (happy path, Pulumi failure, DB failure)
2. Add 5 infrastructure failure tests (throttle, capacity, timeout, permissions, quota)
3. Enhance 2 plan tests to validate rendered scripts

### Week 2: Improve Coverage
4. Add E2E test for basic scenario (attacker + victim)
5. Add E2E test for DC scenario (DC + domain join)
6. Add concurrency test (5 parallel instances)

### Week 3: Refactor & Quality
7. Split conftest.py into focused modules
8. Create failure simulation library
9. Add mutation testing to CI pipeline

### Week 4: Long-term Foundation
10. Add contract tests for AWS APIs
11. Add property-based tests for CIDR allocation
12. Document testing strategy in TESTING.md

---

## 17. Final Verdict

**Test Quality**: B- (Good foundations, meaningful gaps)
**Coverage**: D+ (Executors excellent, main.py nearly untested)
**Production Readiness**: C+ (MVP-ready, not enterprise-ready)

**Key Insight**: The team **understands testing principles** (TDD, fixtures, mocking hygiene) but has **focused on unit-level correctness** at the expense of **integration and failure resilience**. This is common in fast-moving startups but needs course correction before scaling.

**Recommended Action**: Dedicate 1 engineer for 2-3 sprints to fill the critical gaps. Focus on:
1. Main.py integration tests
2. Failure scenario coverage
3. E2E smoke tests per scenario

This investment will pay dividends in reduced production incidents and faster debugging.

---

## Appendix A: Test File Inventory

### Provisioner Tests (43 files)
- `conftest.py` (831 lines) - Test infrastructure
- `test_main.py` (152 lines) - Partial main.py coverage
- `test_config.py` (557 lines) - Config loading and validation
- `test_events.py` (357 lines) - SNS event publishing
- `test_aws_executor.py` (271 lines) - AWS SDK wrapper
- `test_ssm_executor.py` (605 lines) - SSM Run Command executor
- `test_ssm_executor_linux.py` (80 lines) - Linux shell script support
- `test_executor_base.py` (20 lines) - Executor protocol
- `test_ngfw_executor.py` (182 lines) - SSH executor for NGFW
- `test_orchestrator_base.py` (142 lines) - Orchestrator protocol
- `test_setup_orchestrator.py` (376 lines) - Setup orchestration
- `test_ops_orchestrator.py` (168 lines) - Ops orchestration
- `test_bootstrap_plan.py` (54 lines) - Windows bootstrap
- `test_linux_bootstrap_plan.py` - Linux bootstrap
- `test_kali_setup_plan.py` - Kali attacker setup
- `test_domain_join_plan.py` - Domain join orchestration
- `test_dc_setup_plan.py` - DC setup (prebaked AMI)
- `test_xdr_agent_install_plan.py` - Windows XDR agent
- `test_linux_xdr_agent_install_plan.py` - Linux XDR agent
- `test_ngfw_provision_plan.py` (206 lines) - NGFW initial config
- `test_ngfw_deprovision_plan.py` - NGFW cleanup
- `test_ngfw_start_plan.py` - NGFW start ops
- `test_ngfw_stop_plan.py` - NGFW stop ops
- `test_ngfw_add_rule_plan.py` - Dynamic security rule add
- `test_ngfw_remove_rule_plan.py` - Dynamic security rule remove
- `test_ngfw_add_address_plan.py` - Dynamic address object add
- `test_ngfw_remove_address_plan.py` - Dynamic address object remove
- `test_ngfw_reconcile_plan.py` - NGFW state reconciliation
- `test_range_pause_plan.py` - Range pause orchestration
- `test_range_resume_plan.py` - Range resume orchestration
- `test_user_ngfw_stack_sweep_plan.py` - User cleanup
- `test_network_component.py` - Pulumi network component
- `test_instance_component.py` - Pulumi instance component
- `test_range_stack.py` (30 lines) - Range stack (placeholder)
- `test_terraform_runner.py` - Terraform execution
- `test_range_ops_ngfw_retry.py` - NGFW ops retry logic
- `test_edge_cases.py` (139 lines) - Config edge cases
- `test_setup_integration.py` (168 lines) - Setup integration
- `test_tags.py` - AWS resource tagging
- `test_user_data.py` - EC2 user data rendering
- `test_catalog.py` - Scenario catalog validation
- `test_templates.py` - Jinja2 template rendering
- `test_ngfw_configure_subnets.py` - NGFW subnet config

### Frontend Tests (6 files)
- `dashboard.test.js` (~206 lines)
- `terminal.test.js` (~500+ lines estimated)
- `sidebar.test.js`
- `ngfw.test.js`
- `upload.test.js`
- `xdr-dropdown.test.js`

### CyberScript Tests (6 files)
- `test_events.py` (219 lines) - Event models
- `test_channels.py` - Channel definitions
- `test_enums.py` - Enum types
- `test_schemas.py` - Pydantic schemas
- `test_*.py` (2 more files)

---

## Appendix B: Sample Test Quality Comparison

### Excellent Test (SSMExecutor)
```python
def test_run_command_polls_until_complete(self):
    """run_command polls get_command_invocation until status is terminal."""
    mock_ssm = MagicMock()
    mock_ec2 = MagicMock()
    mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-123"}}

    # Return InProgress twice, then Success
    mock_ssm.get_command_invocation.side_effect = [
        {"Status": "InProgress"},
        {"Status": "InProgress"},
        {"Status": "Success", "ResponseCode": 0, ...},
    ]

    with patch("time.sleep"):
        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.run_command("i-12345", "script", 60)

    assert result.success is True
    assert mock_ssm.get_command_invocation.call_count == 3
```

**Why Excellent**: Tests actual polling logic, simulates multiple states, verifies retry count.

### Weak Test (RangeStack)
```python
def test_stack_can_be_imported(self):
    """RangeStack can be imported from the stacks module."""
    from stacks.range_stack import RangeStack
    assert RangeStack is not None
```

**Why Weak**: Tests import, not behavior. Placeholder that should be deleted or implemented.

### Shallow Test (NGFWProvisionPlan)
```python
def test_delete_allow_all_rule_removes_default_rule(self):
    """Delete allow-all step should remove the default allow-all rule."""
    from plans.ngfw_provision import NGFWProvisionPlan

    plan = NGFWProvisionPlan()
    delete_step = next(s for s in plan.steps if "allow_all" in s.name)

    assert "delete rulebase security rules allow-all" in delete_step.stdin_input
```

**Why Shallow**: Tests script contains string, not that script is syntactically correct or actually works on NGFW.

---

**End of Report**
