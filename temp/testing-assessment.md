# Shifter Testing Quality & Coverage Assessment

**Date:** 2026-02-07 | **Rating: ADEQUATE (6/10)** | **Trajectory: Good foundations, critical gaps**

---

## Executive Summary

Shifter has ~150 test files with roughly 34,000 lines of test code - a substantial investment. The testing culture is evident: consistent patterns, clear naming, comprehensive docstrings, and thoughtful fixture design. The **Django platform tests rate GOOD (7.5/10)** with strong service-layer coverage and proper integration test separation. The **provisioner tests rate NEEDS WORK (5/10)** with excellent executor tests but only ~5% coverage of the critical 2,911-line main.py.

The systemic issue across both suites is a **testing the mock, not the system** pattern. Platform tests mock the entire ORM layer, verifying `mock.assert_called_once_with(id=42)` instead of testing that the right data comes back from a real database. Provisioner plan tests verify "does this step name exist" instead of "does this script actually configure the firewall correctly." The tests catch structural regressions but miss behavioral bugs.

There are zero end-to-end tests covering a complete user journey (login -> upload agent -> launch range -> connect terminal -> destroy range). There are zero concurrency tests despite the platform managing concurrent range provisioning with shared subnet pools.

---

## What's Tested Well

### Platform Test Strengths
- **Service layer input validation** (~95% coverage): Every service function tests None user, invalid type, unsaved user. Consistent and thorough.
- **Error propagation paths**: Tests verify exceptions bubble up correctly from model -> service -> view.
- **Integration tests** (4 files, ~2,000 lines): `test_range_lifecycle.py` tests real DB operations with only ECS mocked. `test_services_credentials.py` validates full credential CRUD.
- **Schema validation** (`shared/schemas/`): Comprehensive Pydantic model testing including serialization roundtrips.
- **Test organization**: Mirror of production code structure, integration tests segregated.
- **Naming convention**: `test_returns_empty_list_when_model_returns_empty` - readable without looking at code.

### Provisioner Test Strengths
- **Executor tests (A-grade)**: SSM executor tests (605 lines) simulate polling states, timeouts, retries, and multi-status transitions. AWSExecutor tests validate client caching, error handling, and action dispatch. These are the gold standard for the codebase.
- **Conftest fixtures**: Excellent Pulumi mocking infrastructure with resource tracking.
- **CyberScript tests (A-grade)**: Comprehensive Pydantic event model testing with serialization/deserialization roundtrips.
- **Edge case tests**: Config parsing boundaries, mixed OS types, empty subnets.

### Frontend Test Strengths
- **6 test files** covering dashboard, terminal, sidebar, NGFW, upload, and dropdown.
- Proper WebSocket and xterm.js mocking.
- State management and user interaction coverage.

---

## Critical Coverage Gaps

### 1. No End-to-End User Journey Tests
**Risk: HIGH** | **Effort: MEDIUM (2-3 days)**

No test covers the complete flow: View -> CMS Service -> Engine Service -> Database. Each layer is tested in isolation with mocked boundaries. Integration bugs between layers can only be found in production or manual testing.

### 2. Main.py Coverage: ~5% (Provisioner)
**Risk: CRITICAL** | **Effort: HIGH (1-2 weeks)**

The 2,911-line main.py orchestrates all provisioning, but only 3 helper functions are tested (`parse_serial_number`, `parse_device_certificate_status`, `poll_for_serial_and_cert`). The entire provision/destroy/pause/resume flow, DB state management, NGFW coordination, and error recovery are untested.

### 3. Zero Concurrency Tests
**Risk: HIGH** | **Effort: MEDIUM (3-5 days)**

The platform manages concurrent range provisioning with shared subnet pools protected by `select_for_update()` (platform) and PostgreSQL advisory locks (provisioner). Neither mechanism is tested under contention. Tests verify sequential allocation but not concurrent requests.

### 4. Component/Stack Tests: Placeholder Only (Provisioner)
**Risk: MEDIUM** | **Effort: HIGH**

`test_range_stack.py` contains only `assert RangeStack is not None`. The 932-line NetworkComponent and 792-line InstanceComponent have no meaningful tests. The core IaC logic is essentially untested.

### 5. Plan Tests: Structural, Not Behavioral (Provisioner)
**Risk: MEDIUM** | **Effort: MEDIUM**

18 plan test files verify step ordering and script name existence but never validate:
- Script syntax correctness
- Template rendering with edge case contexts
- Behavior when a step fails mid-plan
- Timeout realism

### 6. Over-Mocking in Platform Service Tests
**Risk: MEDIUM** | **Effort: HIGH (1-2 weeks to refactor)**

~1,530 lines of `test_services_range.py` mock the entire ORM layer. Tests verify `mock_filter.assert_called_once_with(user_id=user.id)` instead of creating real database records and asserting on returned data. This creates brittle tests that pass when code is wrong and fail when implementation changes.

### 7. Missing Error Recovery Tests
**Risk: MEDIUM** | **Effort: MEDIUM**

No tests simulate:
- ECS task failure mid-provisioning
- Partial instance provisioning failure (3 of 5 succeed)
- Database transaction rollback scenarios
- AWS API throttling during provisioning
- NGFW SSH available but serial number never appears

---

## Anti-Patterns Observed

### Platform Tests
1. **Testing mock calls instead of behavior**: `mock_get.assert_called_once_with(id=42)` tests implementation, not outcomes.
2. **Over-testing impossible conditions**: Tests for Django ORM returning None after `.get()` - mirrors the production code anti-pattern.
3. **Micro-tests**: Many tiny tests each with inline mock setup (noted in CLAUDE.md as causing OOM at 27GB+).
4. **Duplicate fixtures**: `user` fixture defined independently in 10+ test files instead of shared conftest.
5. **Hardcoded magic values**: `range_id=42`, `file_size_bytes=50000000` without named constants.

### Provisioner Tests
1. **Placeholder tests**: `assert RangeStack is not None` - either implement or delete.
2. **831-line conftest**: Suggests tests need too much scaffolding to run.
3. **No failure simulation library**: Each test recreates `ClientError` mocks independently.
4. **Mock call count assertions**: `assert mock.call_count == 3` is brittle and tests implementation.

---

## Test Quality by Component

| Component | Grade | Lines | Notes |
|-----------|-------|-------|-------|
| Platform CMS services | B | 5,000+ | Thorough but over-mocked |
| Platform engine services | B+ | 1,500+ | Good transaction testing |
| Platform mission control | B | 2,500+ | Good API testing, missing WebSocket edge cases |
| Platform schemas | A | 2,000+ | Comprehensive Pydantic validation |
| Platform integration | B+ | 2,000+ | Real DB, properly scoped mocking |
| Provisioner executors | A | 1,100+ | Logic-focused, excellent edge cases |
| Provisioner orchestrators | B+ | 544 | Good sequencing, missing failure scenarios |
| Provisioner plans | C | 2,500 | Structural only - shallow |
| Provisioner main.py | F | 152 | 5% coverage of critical code |
| Provisioner components | F | ~30 | Placeholder only |
| CyberScript | A | 500+ | Production-quality Pydantic testing |
| Frontend JS | B+ | 2,900+ | Well-structured, unknown depth |

---

## Recommendations (4-Week Roadmap)

### Week 1: Fill Critical Gaps
1. Write 3 main.py integration tests (happy path, Pulumi failure, DB failure)
2. Add concurrency test for subnet allocation under contention
3. Add end-to-end test: upload agent -> launch range -> destroy range

### Week 2: Improve Coverage
4. Add 5 infrastructure failure tests (throttle, capacity, timeout, permissions, quota)
5. Enhance 3 plan tests to validate rendered script syntax
6. Add partial failure test (3 of 5 instances fail)

### Week 3: Reduce Brittleness
7. Refactor 2 platform service test files to use real DB instead of mocked ORM
8. Consolidate duplicate fixtures into shared conftest
9. Parameterize repeated validation tests

### Week 4: Foundation
10. Split provisioner conftest.py into focused modules
11. Create shared failure simulation library
12. Delete or implement placeholder tests

---

## FAANG Benchmark Comparison

| Metric | Shifter | FAANG Typical | Gap |
|--------|---------|---------------|-----|
| Line coverage (platform) | ~60-70% est. | 80%+ | Moderate |
| Line coverage (provisioner main.py) | ~5% | 80%+ | Critical |
| E2E tests | 0 | 5-10 critical paths | Critical |
| Concurrency tests | 0 | Per shared resource | High |
| Failure injection | None | Framework-level | High |
| Mutation testing | None | CI-integrated | Medium |

**Assessment:** The test suite is adequate for early-stage product but 2-3 maturity levels behind enterprise infrastructure standards. The good news is the testing culture and patterns are solid - the investment is in coverage breadth, not learning testing fundamentals.

---

## Raw Data
- Platform test details: `temp/raw-test-platform.md`
- Provisioner test details: `temp/raw-test-provisioner.md`
