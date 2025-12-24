---
name: tdd-plan
description: Plan and execute work using strict TDD methodology with phase-based checklists. Use when starting any implementation work that needs tests first, phased delivery, and checkpoint reviews.
---

# TDD Planning Workflow

Execute work using strict Test-Driven Development with phase-based checklists and mandatory review stops.

## User Input

```text
$ARGUMENTS
```

Consider any user input before proceeding.

## Core Principles

1. **Tests First**: Write tests BEFORE implementation code
2. **Red-Green-Refactor**: Tests must be shown failing before implementation begins
3. **Phase Gates**: Stop at end of each phase for user review
4. **Checklist Tracking**: Items checked off as completed
5. **User Controls Git**: NEVER commit - user handles all git operations

---

## Workflow

### Step 1: Analyze the Task

1. Read and understand the user's request
2. Identify the scope and components involved
3. Review existing code patterns in the repository
4. Identify relevant test files and patterns

### Step 2: Create Phase Plan

Break work into phases. Use TodoWrite to create a checklist with this structure:

**Example Phase Structure:**
```
Phase 1: Test Setup
- [ ] Write test file(s) for new functionality
- [ ] Define test cases covering happy path
- [ ] Define test cases covering edge cases
- [ ] Define test cases covering error conditions
- [ ] Run tests - VERIFY ALL FAIL (red)

Phase 2: Core Implementation
- [ ] Implement minimum code to pass tests
- [ ] Run tests - VERIFY ALL PASS (green)
- [ ] Refactor if needed (keep tests green)

Phase 3: Integration (if applicable)
- [ ] Write integration tests
- [ ] Run integration tests - VERIFY FAIL
- [ ] Implement integration code
- [ ] Run all tests - VERIFY PASS

Phase N: [Additional phases as needed]
```

### Step 3: Execute Each Phase

For EACH phase:

1. **Work through checklist items sequentially**
2. **Mark items complete as you go** using TodoWrite
3. **Show test output** when running tests (especially failures)

### Step 4: Phase Completion Gate (MANDATORY)

At the END of EVERY phase, you MUST complete this checklist:

```markdown
## Phase [N] Completion Gate

### Work Verification
- [ ] All phase checklist items completed
- [ ] Tests written/updated as required
- [ ] Test results shown (red before impl, green after)

### Quality Checks
- [ ] Security review: No hardcoded secrets, no injection vulnerabilities, proper input validation
- [ ] Architecture consistency: Follows existing repo patterns and structure
- [ ] Best practices: Clean code, no unnecessary complexity or bloat
- [ ] No scope creep: Only implements what was requested

### Status
- Tests passing: [YES/NO]
- Ready for review: [YES/NO]
```

Then output:

```
---
PHASE [N] COMPLETE - STOPPING FOR REVIEW

Completed:
- [summary of what was done]

Test Status:
- [test results summary]

Quality Checks:
- Security: [PASS/issues found]
- Architecture: [PASS/issues found]
- Best practices: [PASS/issues found]

AWAITING USER REVIEW
- Review the changes
- Perform git operations (add, commit)
- Say "continue" to proceed to next phase
---
```

**YOU MUST STOP AND WAIT** for user acknowledgment before proceeding.

---

## TDD Test Execution Rules

### Before Implementation (Red Phase)
```bash
# Run tests and show they FAIL
# Output must show failing tests
```

**You MUST show:**
- Test command executed
- Failure output
- Count of failing tests

### After Implementation (Green Phase)
```bash
# Run tests and show they PASS
```

**You MUST show:**
- Test command executed
- Passing output
- Count of passing tests

---

## Security Checklist Items

Always verify at each phase gate:

- [ ] No hardcoded credentials, API keys, or secrets
- [ ] No SQL injection vulnerabilities (use parameterized queries)
- [ ] No XSS vulnerabilities (proper output encoding)
- [ ] No command injection (proper input sanitization)
- [ ] Proper authentication/authorization checks
- [ ] Sensitive data not logged
- [ ] Input validation on all external inputs

---

## Architecture Consistency Items

Always verify at each phase gate:

- [ ] File placement matches existing structure
- [ ] Naming conventions match existing patterns
- [ ] Import style matches existing code
- [ ] Error handling matches existing patterns
- [ ] Test structure matches existing test files
- [ ] Configuration approach matches existing patterns

---

## Best Practices Items (No Bloat)

Always verify at each phase gate:

- [ ] Only implements requested functionality
- [ ] No speculative features or "nice to haves"
- [ ] No unnecessary abstractions
- [ ] No over-engineering
- [ ] Minimal code that solves the problem
- [ ] No unnecessary comments (code is self-documenting)
- [ ] No unnecessary type annotations beyond what exists

---

## Example Execution Flow

**User Request:** "Add email validation to user registration"

**Phase 1: Tests**
```
Working on Phase 1: Tests

- [X] Create test_email_validation.py
- [X] Write test for valid email formats
- [X] Write test for invalid email formats
- [X] Write test for empty email
- [X] Run tests - showing failures:

$ pytest tests/test_email_validation.py -v
FAILED test_valid_email - AssertionError
FAILED test_invalid_email - AssertionError
FAILED test_empty_email - AssertionError
3 failed

RED PHASE COMPLETE - All tests failing as expected
```

[Phase 1 Completion Gate - STOP]

**Phase 2: Implementation**
```
Working on Phase 2: Implementation

- [X] Add validate_email() function
- [X] Handle valid formats
- [X] Handle invalid formats
- [X] Handle empty input
- [X] Run tests - showing passes:

$ pytest tests/test_email_validation.py -v
PASSED test_valid_email
PASSED test_invalid_email
PASSED test_empty_email
3 passed

GREEN PHASE COMPLETE - All tests passing
```

[Phase 2 Completion Gate - STOP]

---

## Important Reminders

1. **NEVER skip the phase gate** - Always stop for user review
2. **NEVER commit** - User handles all git operations
3. **ALWAYS show test output** - Both failures and successes
4. **ALWAYS check off items** - Use TodoWrite to track progress
5. **ALWAYS run quality checks** - Security, architecture, best practices
6. **Keep it simple** - Minimum code to pass tests, no extras
