---
name: test-review
description: Review test quality without reading implementation code. Use when evaluating test files for logic flaws, coverage gaps, assertion strength, and test hygiene. Produces actionable report with prioritized fixes.
---

# Test Quality Review

Review test files for quality issues **without referencing implementation code**. This ensures tests are evaluated on their own merit as specifications of behavior.

## Arguments

```
/test-review <test_file_path> [--fix]
```

- `test_file_path`: Path to the test file to review (required)
- `--fix`: Apply recommended fixes after review (optional)

---

## Review Process

### Phase 1: Read and Catalog

1. Read the test file completely
2. **DO NOT read the implementation code** - tests should stand alone as behavior specs
3. Catalog all test classes and test methods
4. Note fixtures and helper functions

### Phase 2: Evaluate Each Test

Apply the **6 Quality Criteria** to each test:

| Criterion | Question | Fail Indicators |
|-----------|----------|-----------------|
| **Logical** | Does the test verify what its name claims? | Name/assertion mismatch, setup doesn't match assertion |
| **Substantive** | Does it test real behavior or just surface? | Only checks status codes, no state verification |
| **Preventative** | Would a buggy implementation pass? | Loose assertions, missing edge cases |
| **Unique** | Is this duplicating another test? | Same setup/assertion as another test |
| **Isolated** | Does it test one thing? | Multiple unrelated assertions, complex setup |
| **Real** | Does it hit actual code paths? | Over-mocked, trivial pass conditions |

### Phase 3: Detect Anti-Patterns

Scan for these specific issues:

#### HIGH Severity

| Anti-Pattern | Example | Fix |
|--------------|---------|-----|
| **Logic Flaw** | Testing user isolation by creating data for user2 only, proving empty list not isolation | Create data for BOTH users, verify user1 only sees their own |
| **Security Gap** | Missing user isolation test for sensitive endpoint | Add `test_404_for_other_users_*` test |
| **State Not Verified** | POST creates record but test only checks status code | Add `assert Model.objects.filter(...).exists()` |
| **Wrong Thing Tested** | Test name says "validates X" but only checks `"error" in response` | Assert specific field error message |

#### MEDIUM Severity

| Anti-Pattern | Example | Fix |
|--------------|---------|-----|
| **Loose Assertion** | `assert "error" in data` | `assert data["error"] == "Name is required"` |
| **HTML Content Check** | `assert "Ready" in content or "ready" in content` | `assert obj.status == Status.READY` via context |
| **Magic Numbers** | `args=[99999]` for non-existent ID | `max_id = Model.objects.order_by("-id").first().id or 0; args=[max_id + 1]` |
| **Duplicate Test** | Two tests doing same POST with same assertions | Consolidate into single test with all assertions |
| **Ambiguous Status** | `assert status in [A, B]` without documenting why | Pick expected status or document both as valid |

#### LOW Severity

| Anti-Pattern | Example | Fix |
|--------------|---------|-----|
| **Missing Docstring** | Test method with no docstring | Add clear docstring explaining what behavior is verified |
| **Fixture Overuse** | Test creates its own data when fixture exists | Use existing fixture |
| **Assertion Order** | Status code checked after data assertions | Check status code first (fail fast) |

### Phase 4: Identify Coverage Gaps

Check for missing tests:

1. **CRUD completeness** - Create, Read, Update, Delete all tested?
2. **Auth boundaries** - Login required? User isolation?
3. **Validation** - Required fields? Invalid input? Type errors?
4. **State transitions** - All valid transitions? Invalid transitions rejected?
5. **Edge cases** - Empty input? Max length? Null values?
6. **Error paths** - 400, 404, 403, 500 scenarios?

### Phase 5: Generate Report

Produce structured output:

```markdown
# Test Review: <filename>

## Summary
- Total tests: X
- Issues found: Y (H high, M medium, L low)
- Coverage gaps: Z
- Score: XX/100

## Issues by Severity

### HIGH
1. **[Test Name]** - <issue description>
   - Current: `<code snippet>`
   - Fix: `<corrected code>`

### MEDIUM
...

### LOW
...

## Coverage Gaps
1. Missing test for <scenario>
2. ...

## Recommendations
1. <prioritized action>
2. ...
```

---
## Fix Mode

When `--fix` is specified:

1. Apply fixes in priority order (HIGH → MEDIUM → LOW)
2. Run tests after each fix to verify no regressions
3. Stop if any test fails
4. Report what was fixed and what remains

**Fix Rules:**
- Never change test intent, only strengthen assertions
- Never delete tests, only consolidate duplicates
- Always preserve security tests (user isolation)
- Add missing tests for coverage gaps

---

## Example Review

**Input:** `tests/test_user_views.py`

**Finding:** Logic flaw in isolation test

```python
# BEFORE - Proves empty list, not isolation
def test_excludes_other_users_data(self, user, user2, db):
    OtherModel.objects.create(user=user2, name="Other")
    client = get_authenticated_client(user)
    response = client.get(reverse("my_list"))
    assert len(response.context["items"]) == 0  # user has no items!
```

```python
# AFTER - Proves actual isolation
def test_excludes_other_users_data(self, user, user2, db):
    # Create for user1 (requesting user)
    OtherModel.objects.create(user=user, name="Mine")
    # Create for user2
    OtherModel.objects.create(user=user2, name="Other")

    client = get_authenticated_client(user)
    response = client.get(reverse("my_list"))

    items = list(response.context["items"])
    assert len(items) == 1
    assert items[0].name == "Mine"
    assert items[0].user_id == user.id
```

---

## Checklist for Reviewers

Before marking review complete:

- [ ] Read entire test file
- [ ] Did NOT read implementation code
- [ ] Evaluated each test against 6 criteria
- [ ] Scanned for all anti-patterns
- [ ] Identified coverage gaps
- [ ] Generated severity-ranked report
- [ ] Calculated quality score
- [ ] Listed actionable recommendations

---

## When to Use This Skill

- After completing a feature with tests
- Before merging a PR with test changes
- When inheriting a codebase with existing tests
- During test suite maintenance
- When test failures seem inconsistent with code changes
