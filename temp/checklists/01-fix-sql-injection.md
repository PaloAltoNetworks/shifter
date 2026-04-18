# Checklist: Fix SQL Injection in `update_range_status()`

**Priority:** CRITICAL | **Effort:** Small (1-2 hours) | **Risk if deferred:** Exploitable SQL injection

---

## Context

`provisioner/main.py:275-302` constructs column names from `**kwargs` keys using f-strings:

```python
for key, value in kwargs.items():
    updates.append(f"{key} = %s")     # Column name NOT parameterized
sql = f"UPDATE mission_control_range SET {', '.join(updates)} WHERE id = %s"
```

Values are parameterized via `%s`, but **column names cannot be parameterized** in SQL. The code relies on callers passing only hardcoded kwargs. A `# nosec B608` comment suppresses Bandit, creating false confidence.

**Current callers** (all in `range_ops.py`, all hardcoded):
- Line 575: `update_range_status(range_id, "failed", error_message=error_msg)`
- Line 589: `update_range_status(range_id, "paused", paused_at="NOW()")`
- Line 648: `update_range_status(range_id, "failed", error_message=error_msg)`
- Line 700: `update_range_status(range_id, "failed", error_message=error_msg)`
- Line 714: `update_range_status(range_id, "ready", ready_at="NOW()")`

Additional callers exist in `main.py` itself for provision/destroy flows.

---

## Pre-Work

- [ ] Read `provisioner/main.py:275-302` (the `update_range_status` function)
- [ ] Read `provisioner/range_ops.py` and search for all `update_range_status` call sites
- [ ] Search `main.py` for all `update_range_status` call sites
- [ ] Catalog every unique kwarg key passed across ALL call sites
- [ ] Verify `psycopg.sql` is already imported (`from psycopg import sql` at line 21)
- [ ] Read the Django model `mission_control/models.py` to confirm valid column names

## Implementation

- [ ] Define `ALLOWED_COLUMNS` frozenset at module level, immediately above the function:
    ```python
    ALLOWED_COLUMNS = frozenset({
        "status", "error_message", "paused_at", "ready_at", "destroyed_at",
        "provisioned_instances", "ngfw_instance_id", "updated_at",
        "subnet_id",  # include any others found in call site catalog
    })
    ```
- [ ] Add validation at the top of the kwargs loop:
    ```python
    for key, value in kwargs.items():
        if key not in ALLOWED_COLUMNS:
            raise ValueError(f"Invalid column name: {key}")
    ```
- [ ] Replace f-string column interpolation with `psycopg.sql.Identifier()`:
    ```python
    from psycopg import sql as psycopg_sql

    updates = [psycopg_sql.SQL("{} = %s").format(psycopg_sql.Identifier("status")),
               psycopg_sql.SQL("{} = NOW()").format(psycopg_sql.Identifier("updated_at"))]
    ```
- [ ] Handle the `NOW()` special case safely (use `psycopg_sql.SQL("NOW()")`, not string interpolation)
- [ ] Compose the final query with `psycopg_sql.SQL(...).join(updates)` instead of `', '.join()`
- [ ] Remove the `# nosec B608` and `# noqa: S608` comments (the fix eliminates the finding)

## Verification

- [ ] Search the entire provisioner codebase for other f-string SQL patterns:
    - `f"UPDATE`
    - `f"SELECT`
    - `f"INSERT`
    - `f"DELETE`
- [ ] For each match, assess whether it has the same column-name injection risk
- [ ] Run existing provisioner tests: `cd provisioner && python -m pytest`
- [ ] Write a unit test that passes a malicious kwarg key (e.g., `"status = 'hacked'; DROP TABLE mission_control_range; --"`) and verify it raises `ValueError`
- [ ] Write a unit test for the happy path with each allowed column
- [ ] Run `bandit -r provisioner/main.py` and confirm no B608 findings remain
- [ ] Manually verify the function still works by tracing through one call site end-to-end

## Post-Work

- [ ] Check `range_ops.py` for the same pattern (it imports `update_range_status` from main, so it's covered, but check for any local SQL construction)
- [ ] Check `config.py` and `components/network.py` for similar dynamic SQL patterns
- [ ] Update the `# nosec` comment inventory if the project tracks these
