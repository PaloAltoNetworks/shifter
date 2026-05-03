# Experiment Manager Code Review

## Executive Summary

The experiment manager is **significantly better** than the scenario editor at the time of its initial review, but still falls short of the CMS services.py bar in several areas. The code is functional, well-structured architecturally, and demonstrates good understanding of Django/async patterns. However, it lacks the defensive rigor and comprehensive logging present in the mature CMS services layer.

**Overall assessment:** Production-ready with moderate risk. No critical blocking bugs found, but needs hardening before heavy use.

---

## Exception Handling (Below bar, but not broken)

### Status: Moderate Gap

**What's good:**
- Has a proper exception hierarchy that extends `ExperimentError` (base class)
- Specific exception types for different failure modes: `ScriptUploadError`, `ExperimentValidationError`, `ExperimentStateError`, `ArtifactError`
- Services layer catches specific exceptions and re-raises domain errors

**What's missing:**

#### 1. Does NOT extend CMSError

```python
class ExperimentError(Exception):
    """Base exception for experiment operations."""
```
`exceptions.py`, lines 4-5

The scenario editor made this same mistake initially. `ExperimentError` should extend `CMSError` from `shared.exceptions` to integrate with the shared exception hierarchy. Any middleware or handlers that catch `CMSError` won't catch experiment errors.

**Impact:** Low-medium. Experiment errors will propagate as generic exceptions rather than being handled by CMS error handling patterns. Inconsistent with the rest of the platform.

**Fix:** Change to `class ExperimentError(CMSError):`

#### 2. Incomplete exception wrapping in services

Most service functions catch expected exceptions and re-raise domain errors, but some edge cases aren't covered:

```python
def get_experiment(user: User, experiment_id: int) -> Experiment:
    try:
        return (
            Experiment.objects.prefetch_related("runs__artifacts", "scripts__script")
            .get(pk=experiment_id, user=user)
        )
    except Experiment.DoesNotExist:
        logger.warning("get_experiment: not found experiment_id=%s user_id=%s", experiment_id, user.pk)
        raise ExperimentError("Experiment not found")
```
`services.py`, lines 213-234

Good: Catches `DoesNotExist` and raises domain error.
Missing: No catch-all for unexpected exceptions. If `prefetch_related` fails due to a database error, it propagates as a raw Django exception.

Compare to CMS `get_agent` (services.py:342-465):
```python
    except (TypeError, CMSError):
        raise
    except Exception:
        logger.exception(
            "Error in get_agent for user_id=%s, agent_id=%s",
            user.id,
            agent_id,
        )
        raise
```

The CMS pattern catches all unexpected exceptions, logs them with full context, and re-raises. This ensures every error is logged before propagating. The experiment manager only does this in some functions (e.g., `create_experiment` does it correctly at line 249-262).

**Impact:** Medium. Unexpected errors (database connection failures, ORM bugs) won't be logged with context, making production debugging harder.

#### 3. Views have incomplete exception handling

```python
@staff_member_required
def experiment_detail(request: HttpRequest, experiment_id: int) -> HttpResponse:
    try:
        experiment = services.get_experiment(cast("User", request.user), experiment_id)
    except ExperimentError:
        messages.error(request, "Experiment not found.")
        return redirect("experiments:experiment_list")

    return render(request, ...)
```
`views.py`, lines 184-200

Only catches `ExperimentError`. If `get_experiment` raises a different exception type (database error, ORM bug), it propagates as an unhandled 500. The scenario editor had the same issue.

**Fix:** Add a catch-all `except Exception` block that logs and shows a generic error message.

---

## Logging (Moderate Gap)

### Status: Inconsistent — better than scenario editor, not as good as CMS

**What's good:**
- Services layer has structured logging with context (user_id, experiment_id, etc.)
- Uses `logger.info()` for successful operations
- Uses `logger.warning()` for expected errors (not found, validation failures)
- Uses `logger.error()` for unexpected S3/external service failures
- Views use Django messages framework for user feedback

**What's missing:**

#### 1. No debug entry points in services

CMS pattern (services.py:395-404):
```python
def get_agent(user: User, agent_id: int) -> AgentConfig:
    """Get a single agent by ID. Validate ownership and check soft-delete."""
    logger.debug(
        "get_agent called with user_id=%s, agent_id=%s",
        user.id,
        agent_id,
    )
    _validate_user(user, "get_agent")
```

Every CMS service function logs entry with parameters at debug level. The experiment manager does this inconsistently:
- `initiate_script_upload`: Has debug log at line 106 (after success, not at entry)
- `create_experiment`: No debug entry log
- `get_experiment`: No debug entry log

**Impact:** Low. Makes debugging harder when tracing execution flow, but not critical.

#### 2. Views have minimal logging

```python
@staff_member_required
def script_upload(request: HttpRequest) -> HttpResponse:
    """Upload a script file — two-step presigned URL flow."""
    if request.method == "GET":
        return render(request, "experiments/script_upload.html", {"active_nav": "experiments"})
    # ... 30 lines of logic with zero logging ...
```
`views.py`, lines 54-92

The views only use `messages` for user feedback. No `logger.info()` when operations succeed, no `logger.warning()` when validation fails. Compare to the scenario editor which had **zero logging in views**—at least here the services layer logs, so operations are traceable, but view-level context (HTTP method, POST data validation) is lost.

**Impact:** Low-medium. Harder to debug production issues that only manifest at the HTTP layer.

#### 3. Orchestrator logging is good

```python
logger.info(
    "schedule_runs: scheduled %d runs for experiment %s",
    scheduled, self.experiment_id,
)
```
`orchestrator.py`, line 159-162

The orchestrator has comprehensive logging with context. This is the right pattern.

---

## Validation & Defensive Coding (Significant Gap)

### Status: Well below CMS bar

**What's good:**
- Pydantic schemas validate input structure (`ExperimentCreateInput`, `ScriptAssignmentInput`, `ScriptUploadInput`)
- Services layer validates business logic (scenario exists, instances match, scripts belong to user)
- Models have `clean()` methods with validation (`Experiment.clean()` checks `max_parallel_runs <= total_runs`)
- State transitions use allowlist pattern (`EXPERIMENT_TRANSITIONS`, `RUN_TRANSITIONS`)

**What's missing:**

#### 1. No user parameter validation anywhere

CMS pattern (services.py:368-394, extracted to `_validate_user` helper):
```python
def _validate_user(user: User, func_name: str) -> None:
    if user is None:
        logger.error("%s called with None user", func_name)
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error("%s: user missing id attribute, got %s", func_name, type(user).__name__)
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")
    if user.id is None:
        logger.error("%s: user.id is None", func_name)
        raise ValueError(USER_MUST_BE_SAVED)
    logger.debug("%s: user_id=%s validated", func_name, user.id)
```

Every CMS service function calls this at the top. The experiment manager services have **zero user validation**:

```python
def list_scripts(user: User) -> QuerySet[ScriptAsset]:
    """List active (non-deleted) scripts for a user."""
    return ScriptAsset.objects.filter(user=user, deleted_at__isnull=True).order_by("-created_at")
```
`services.py`, lines 59-68

If `user=None` is passed, this fails with `AttributeError: 'NoneType' object has no attribute 'id'` when Django ORM tries to build the query. Should fail with a clear `TypeError("user cannot be None")`.

**Impact:** Medium-high. Makes debugging harder when bugs occur. Instead of getting a clear error message at the service layer boundary, you get an opaque Django ORM error deep in the stack.

**Fix:** Add a `_validate_user()` helper matching the CMS pattern and call it in every service function that takes a `user` parameter.

#### 2. No response type validation

CMS pattern (services.py:406-426):
```python
    agent = AgentConfig.objects.get(id=agent_id)

    if agent is None:
        logger.error("get_agent: model returned None for agent_id=%s", agent_id)
        raise TypeError("Model returned None instead of AgentConfig")

    if not isinstance(agent, AgentConfig):
        logger.error("get_agent: model returned invalid type %s", type(agent).__name__, agent_id)
        raise TypeError(f"Model returned {type(agent).__name__}, expected AgentConfig")
```

The CMS validates that ORM calls return the expected type. The experiment manager assumes the ORM always works:

```python
def get_experiment(user: User, experiment_id: int) -> Experiment:
    try:
        return (
            Experiment.objects.prefetch_related("runs__artifacts", "scripts__script")
            .get(pk=experiment_id, user=user)
        )
    except Experiment.DoesNotExist:
        raise ExperimentError("Experiment not found")
```

No validation that the return value is actually an `Experiment` instance. In normal operation this is fine, but the CMS pattern guards against Django ORM bugs, monkey-patching during tests, or database corruption.

**Impact:** Low. Unlikely to matter in practice, but inconsistent with CMS defensive philosophy.

#### 3. No `full_clean()` before save

CMS pattern (not shown explicitly but implied by test failures when this is skipped): Call `model.full_clean()` before `model.save()` to run model-level validation.

Experiment manager:
```python
    experiment = Experiment.objects.create(
        user=user,
        name=data.name,
        description=data.description,
        scenario_id=data.scenario_id,
        agent=agent,
        total_runs=data.total_runs,
        max_parallel_runs=data.max_parallel_runs,
    )
```
`services.py`, lines 286-294

`Experiment.clean()` exists (models.py:144-150) and validates `max_parallel_runs <= total_runs`, but it's never called because there's no `experiment.full_clean()` before the implicit save in `objects.create()`.

**However:** Pydantic schema validation covers this (schemas.py:151-156):
```python
    @model_validator(mode="after")
    def validate_parallel_vs_total(self) -> ExperimentCreateInput:
        if self.max_parallel_runs > self.total_runs:
            raise ValueError("max_parallel_runs cannot exceed total_runs")
        return self
```

So this is redundant defense, not a gap. The Pydantic validation happens first and would catch this. But if someone bypasses the service layer (e.g., Django admin, shell), the model-level validation never runs.

**Impact:** Low. Redundant validation is good defense-in-depth, but not critical.

#### 4. Views parse JSON without defensive error handling

```python
    scripts_json = request.POST.get("scripts_json", "[]")
    scripts_data = json.loads(scripts_json) if scripts_json else []
```
`views.py`, line 157-158

If `scripts_json` is malformed (invalid JSON), `json.loads()` raises `JSONDecodeError`. The outer try/except at line 155 catches this and shows a generic error, so it doesn't crash. But the error message is misleading: "Invalid input: {json error}" — not clear to the user what went wrong.

Compare to scenario editor which had the same issue—the JS serializes data into a hidden field, if that fails, the user sees a cryptic error.

**Impact:** Low. Works correctly, just poor UX on edge cases.

---

## Architectural Consistency

### Status: **Excellent** — better than scenario editor

**Strengths:**

1. **Integrated properly as a Django app within the CMS structure**
   - Lives at `shifter_platform/experiments/`
   - Not a standalone external app like scenario_editor was initially
   - Clean import structure: `from experiments import services`, `from experiments.models import ...`

2. **Follows established patterns:**
   - Service layer pattern (services.py as business logic boundary) ✓
   - Pydantic for input validation ✓
   - Soft-delete pattern (deleted_at field on ScriptAsset) ✓
   - State machine pattern with explicit transitions ✓
   - Presigned URL pattern for S3 uploads (matches cms/assets) ✓
   - HMAC-signed tokens for upload verification (matches cms/assets/upload_token.py) ✓

3. **WebSocket integration follows mission_control pattern:**
   - Consumer structure matches RangeStatusConsumer
   - Channel groups for per-experiment broadcasting
   - Authentication and ownership validation
   - Hydration on connect

4. **SQS event handler follows engine/cms pattern:**
   - Handler dispatch table
   - SNS envelope unwrapping
   - Event type routing
   - Broadcasting to WebSocket consumers

5. **Orchestrator follows SetupOrchestrator pattern:**
   - Lifecycle management
   - State machine enforcement
   - Run scheduling with parallelism limits
   - Error handling with per-run failure tracking

6. **Template structure is consistent:**
   - Uses XDR dark theme CSS variables
   - Consistent styling with scenario_editor
   - Has its own base.html (scenario_editor pattern, not site-wide base)

**Weaknesses:**

1. **No tests for template JavaScript**
   - The scenario editor had a critical JS serialization bug (Python→JS) that broke the form editor
   - The experiment manager uses the same pattern at experiment_create.html line 191: `const scripts = {{ scripts|safe }};`
   - If `scripts` is a Python list of dicts, `|safe` will output Python repr syntax, not JSON
   - However, in this case `scripts` comes from `services.list_scripts()` which returns a QuerySet, then passed to template as is
   - The template never actually uses this variable! It's loaded but never referenced in the JS
   - **This is dead code** — should be removed or the feature completed

2. **Template variable validation is pre-runtime only**
   - `template_vars.validate_template()` checks that instance names in prompts match the scenario
   - But this validation is never called anywhere
   - `resolve_template()` will fail at runtime if a variable is invalid, but that's during orchestration, not at creation time
   - User can save an experiment with `{{NonExistent.ip}}` and won't find out until execution

3. **Artifact collection is stubbed**
   - `orchestrator._collect_artifacts()` just logs, doesn't actually dispatch ECS tasks
   - `orchestrator._dispatch_commands()` just logs
   - `orchestrator._request_range_provisioning()` just logs
   - Comment at line 10 says "Actual SSM commands are dispatched via ECS tasks (portal lacks SSM permissions)"
   - This is intentional (integration pending), but means the orchestrator can't actually run experiments yet

**Comparison to scenario_editor issues:**
- ✓ No separate app outside CMS structure (experiment manager is inside shifter_platform)
- ✓ No duplicate test fixtures (uses proper conftest.py patterns)
- ✓ No dual API+template interface (templates only)
- ✓ No XSS vectors (uses Django template escaping, no `innerHTML` injection)

---

## Will It Actually Work? (Functional Assessment)

### Status: **Mostly yes, with integration gaps**

#### What works:

1. **Script upload flow:**
   - Two-phase presigned URL upload ✓
   - Token-based verification ✓
   - Size validation ✓
   - File type validation (.py only) ✓
   - S3 verification after upload ✓
   - Soft-delete ✓

2. **Experiment creation:**
   - Validates scenario exists ✓
   - Validates instance names match scenario ✓
   - Validates script assets exist and belong to user ✓
   - Validates agent exists if specified ✓
   - Creates experiment + script assignments in transaction ✓

3. **State transitions:**
   - DRAFT → QUEUED when started ✓
   - QUEUED → RUNNING when orchestrator schedules ✓
   - Run state machine enforced (PENDING → PROVISIONING → EXECUTING_VICTIMS → EXECUTING_ATTACKER → COLLECTING → COMPLETED) ✓
   - Invalid transitions raise ValueError ✓

4. **Run scheduling:**
   - Respects max_parallel_runs limit ✓
   - Schedules pending runs when slots available ✓
   - Handles run failures and continues ✓
   - Detects experiment completion when all runs terminal ✓

5. **WebSocket status updates:**
   - Connects with authentication ✓
   - Hydrates initial state ✓
   - Receives real-time run status changes ✓
   - Auto-reconnects on disconnect ✓
   - Reloads page when experiment completes ✓

#### What doesn't work yet:

1. **No actual script execution**
   - `_dispatch_commands()` is a stub (orchestrator.py:363-368)
   - `_collect_artifacts()` is a stub (orchestrator.py:370-372)
   - `_request_range_provisioning()` is a stub (orchestrator.py:353-361)
   - Integration with ECS task runner not implemented

2. **No artifact storage**
   - RunArtifact model exists
   - ExperimentArtifact model exists
   - But nothing creates these records yet
   - Download views exist but will always fail with "Artifact not found"

3. **Template variable validation only happens at runtime**
   - User can save a Claude prompt with invalid variables
   - Won't find out until execution
   - Should validate during `create_experiment()` by calling `template_vars.validate_template()`

#### Edge cases and race conditions:

1. **No race condition on experiment creation**
   - Uses `transaction.atomic()` ✓
   - No unique constraint on experiment name (multiple users can have same name) ✓
   - Script assignments created in same transaction ✓

2. **Race condition on concurrent start_experiment calls**
   ```python
   if experiment.status != ExperimentStatus.DRAFT.value:
       raise ExperimentStateError(...)

   with transaction.atomic():
       runs = [...]
       ExperimentRun.objects.bulk_create(runs)
       experiment.transition_to(ExperimentStatus.QUEUED)
   ```
   `services.py`, lines 334-348

   Two concurrent requests can both pass the status check, then both try to create runs and transition. The second one will hit a constraint violation when trying to create duplicate run_number records (unique_experiment_run_number constraint, models.py:244-248).

   **Impact:** Medium. Not wrapped in try/except, so second request fails with raw IntegrityError.
   **Fix:** Move status check inside transaction or add select_for_update.

3. **No pagination on experiment list**
   - All experiments loaded at once (views.py:115, services.py:192-210)
   - Uses `.annotate()` with count aggregates
   - If a user has 1000s of experiments, this is slow
   - But scenario editor had same issue and it's consistent across the codebase (no pagination anywhere)

---

## UX Assessment

### Status: **Good** — on par with rest of platform

**Strengths:**

1. **Consistent XDR dark theme styling**
   - Uses CSS variables (--xdr-text, --xdr-border, --xdr-surface)
   - Status badges with semantic colors
   - Responsive grid layouts

2. **Real-time status updates**
   - WebSocket connection indicator (green dot when connected)
   - Live run status updates without page refresh
   - Auto-reload when experiment completes
   - Graceful reconnection handling

3. **Django messages for feedback**
   - Success/error messages on all actions
   - Preserved on redirect
   - Rendered in consistent message box

4. **Form validation feedback**
   - Required field indicators
   - Input constraints (min/max, maxlength)
   - Hint text under fields
   - Server-side validation errors shown inline

5. **Workflow clarity**
   - Back links on every page
   - Breadcrumb context via page headers
   - Action buttons contextual to state (Start/Cancel/Download)
   - Disabled buttons when action invalid

**Weaknesses:**

1. **No success confirmation on script upload**
   - After client-side upload to S3, JS calls completion endpoint
   - Success message only shows after redirect
   - During S3 upload, no progress indicator
   - If upload fails, error handling is unclear (relies on S3 timeout)

2. **Script assignment UI is clunky**
   - Must click "Add Script" for each assignment
   - No bulk editing
   - No validation until form submit
   - Can't see which instances already have scripts

3. **No template variable validation feedback**
   - User can enter `{{Typo.ip}}` in a Claude prompt
   - No warning at creation time
   - Won't discover error until experiment runs
   - Should validate on blur or form submit

4. **No confirmation on Cancel action**
   - Experiment cancel button is one-click with no confirm dialog
   - Compare to scenario editor delete which had `confirm()`
   - Can't undo a cancel
   - Should add `onclick="return confirm('Cancel this experiment?')"`

5. **Runs table is static until experiment starts**
   - Shows empty table in DRAFT state
   - Could show "Runs will be created when experiment starts"

6. **No download button for individual run artifacts** (yet)
   - Template has download buttons (experiment_detail.html:251-256)
   - But no artifacts exist because collection isn't implemented
   - Once implemented, UX is ready

7. **Error messages are generic**
   - "Experiment not found" doesn't explain why (deleted? wrong user? ID typo?)
   - "Validation failed: {pydantic error}" shows raw Pydantic error (technical jargon)
   - Could be friendlier

---

## Test Coverage

### Status: **Good** — comprehensive unit tests, missing integration tests

**What's tested:**

1. **Services (test_services.py):**
   - Script listing, deletion, ownership
   - Experiment creation, starting, cancellation
   - Scenario validation
   - Script assignment validation
   - State transitions
   - Run creation

2. **Views (test_views.py):**
   - Staff access control
   - List/detail views
   - Create/start/cancel actions
   - Ownership enforcement

3. **Models (test_models.py):**
   - State transitions
   - Model validation (max_parallel vs total_runs)
   - Constraints

4. **Schemas (test_schemas.py):**
   - Pydantic validation
   - Field constraints
   - Model validators

5. **Template vars (test_template_vars.py):**
   - Variable extraction
   - Validation
   - Resolution

6. **Orchestrator (test_orchestrator.py):**
   - Run scheduling
   - Parallelism limits
   - State transitions
   - Completion detection

7. **Handlers (test_handlers.py):**
   - Event routing
   - SNS unwrapping
   - Handler dispatch

8. **S3 tokens (test_s3_tokens.py):**
   - Token generation
   - Token verification
   - Signature validation

**What's NOT tested:**

1. **No integration tests**
   - All tests are unit tests with mocked S3/ECS
   - No end-to-end test that creates an experiment, starts it, and validates the orchestrator flow
   - Compare to scenario editor which had similar gap

2. **No WebSocket consumer tests**
   - Consumer authentication/authorization not tested
   - Hydration not tested
   - Broadcasting not tested

3. **No template rendering tests**
   - Views tests only check status codes and basic content
   - Don't validate JS execution, form serialization, or WebSocket connection logic
   - Scenario editor had critical JS bug that tests didn't catch (Python→JS serialization)

4. **No test for race condition on start_experiment**
   - Two concurrent calls can both pass status check
   - Should test with threading/multiprocessing

5. **No test for S3 upload flow end-to-end**
   - initiate_script_upload is tested
   - complete_script_upload is tested
   - But not the full client-side flow (presigned URL → upload → completion)

---

## Comparison to Scenario Editor Issues

| Issue | Scenario Editor | Experiment Manager |
|-------|----------------|-------------------|
| Exception hierarchy | Disconnected (not extending CMSError) | **Same issue** — ExperimentError doesn't extend CMSError |
| Logging | Zero in views, inconsistent in services | Better — services have structured logging; views use messages |
| User validation | Missing | **Same issue** — no user parameter validation |
| `full_clean()` before save | Missing | Missing but mitigated by Pydantic validation |
| XSS in templates | Yes (innerHTML injection) | No — proper Django escaping |
| Python→JS serialization | Broken (Python repr → JS) | Dead code — scripts variable unused |
| Form validation bypass | Yes (form path weaker than API) | N/A — no separate API path |
| Race conditions | Multiple (IntegrityError on create) | One (start_experiment concurrent calls) |
| Test coverage | Gaps in API/YAML validation | Gaps in integration/WebSocket tests |
| Architecture | Separate app, inconsistent | Integrated, consistent patterns ✓ |

**Overall:** The experiment manager learned from scenario editor mistakes. Most of the critical bugs (XSS, broken JS, inconsistent exception handling) are absent. The remaining issues are refinements, not blockers.

---

## Priority Fixes

### High (should fix before heavy use):

1. **Make ExperimentError extend CMSError** — one-line fix, architectural consistency
2. **Add user validation to all service functions** — use `_validate_user()` pattern from CMS
3. **Add catch-all exception handlers to service functions** — log unexpected errors with context
4. **Add catch-all exception handlers to views** — show generic error page instead of 500
5. **Fix race condition on start_experiment** — wrap status check in transaction or use select_for_update
6. **Validate Claude prompt template variables at creation time** — call `template_vars.validate_template()` in `create_experiment()`
7. **Add confirmation dialog on Cancel button** — `onclick="return confirm(...)"`

### Medium (polish before wider adoption):

8. **Add debug entry logging to all service functions** — match CMS pattern
9. **Add logging to views** — info on success, warning on validation failures
10. **Remove dead code** — scripts variable in experiment_create.html
11. **Improve error messages** — less generic, more actionable
12. **Add integration tests** — full experiment creation → start → completion flow
13. **Add WebSocket consumer tests** — authentication, hydration, broadcasting
14. **Add template rendering tests** — verify JS execution and form serialization

### Low (nice to have):

15. **Add response type validation** — instanceof checks like CMS does
16. **Call model.full_clean() before save** — redundant defense-in-depth
17. **Add progress indicator on script upload** — show upload %
18. **Improve script assignment UI** — bulk editing, validation on blur
19. **Add pagination to experiment list** — when >100 experiments exist

---

## Summary Table

| Area | Rating | Notes |
|------|--------|-------|
| Exception handling | Moderate gap | Doesn't extend CMSError; incomplete catch-all handlers |
| Logging | Moderate gap | Services good, views minimal; missing debug entry points |
| Validation | Significant gap | No user validation; Pydantic is strong but not enough |
| Defensive coding | Moderate gap | Missing response type checks, full_clean |
| Functional correctness | Mostly works | State machine solid; integration stubs present; one race condition |
| Architecture | **Excellent** | Follows all CMS patterns; integrated properly; clean structure |
| UX | Good | Real-time updates; consistent styling; some rough edges |
| Test coverage | Good | Comprehensive units; missing integration and template tests |

**Compared to scenario editor at initial review:**
- Architecture: **Much better** (integrated, consistent)
- Exception handling: **Same** (doesn't extend CMSError)
- Logging: **Better** (services have structured logging)
- Validation: **Same** (no user validation)
- Functional correctness: **Better** (no XSS, no broken JS)
- Test coverage: **Similar** (good units, missing integration)

**Recommendation:** Ship it, but prioritize the 7 high-priority fixes for the next sprint. The code is structurally sound and won't break in production, but needs hardening to match the mature CMS services bar.

---

## Additional Findings

### 1. Orchestrator refresh pattern may mask stale data

```python
def schedule_runs(self) -> int:
    experiment = self.experiment  # Uses cached property
    if experiment.status == ExperimentStatus.QUEUED.value:
        experiment.transition_to(ExperimentStatus.RUNNING)
        self.refresh()  # Reloads from DB
```
`orchestrator.py`, lines 100-110

The orchestrator caches the experiment instance in a property and manually refreshes. If another process modifies the experiment between checks, the cached data is stale. The `refresh()` pattern works, but is error-prone — easy to forget to call it after mutations.

**Better pattern:** Always reload from DB before state checks, or use `select_for_update()` for critical sections.

**Impact:** Low. Only matters if multiple workers process the same experiment concurrently, which shouldn't happen.

### 2. State transition logs to wrong level in models

```python
def transition_to(self, new_status: ExperimentStatus) -> None:
    allowed = EXPERIMENT_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        msg = f"Cannot transition experiment from {current.value} to {new_status.value}"
        logger.warning("Experiment %s: %s", self.pk, msg)  # Warning level
        raise ValueError(msg)
```
`models.py`, lines 112-126

Invalid state transitions log at WARNING level, then raise ValueError. But this is an application logic error, not a warning — should be ERROR level since it indicates a bug (orchestrator trying an invalid transition).

Compare to the scenario editor which had inconsistent error logging. The experiment manager is better but still not quite right.

**Impact:** Low. Logs correctly, just wrong severity.

### 3. No validation on execution_order values

```python
execution_order = models.PositiveIntegerField(
    default=0,
    help_text="Lower = earlier. Victims get 0, attacker gets 100.",
)
```
`models.py`, lines 177-180

The help text says "Victims get 0, attacker gets 100" but there's no enforcement. User can set execution_order=50 and the script assignment falls between victim/attacker phases, which the orchestrator doesn't handle — it checks `< 100` for victims, `>= 100` for attackers (orchestrator.py:328-331).

What happens if execution_order=100? It's an attacker (>= 100). What about execution_order=99? It's a victim (< 100). This is correct per the code, but the help text is misleading ("Victims get 0" implies they should use exactly 0).

**Impact:** Low. Works as coded, just confusing.

### 4. WebSocket consumer error handling is silent

```python
async def experiment_run_status(self, event):
    """Handle run status update broadcast."""
    await self.send(text_data=json.dumps({
        "type": "run_status",
        "run_id": event.get("run_id"),
        "run_number": event.get("run_number"),
        "status": event.get("status"),
        "error_message": event.get("error_message", ""),
    }))
```
`consumers.py`, lines 75-83

No try/except around `json.dumps()` or `send()`. If `event` contains non-serializable data, `json.dumps()` fails and the consumer crashes without logging anything.

**Impact:** Low. Event data is controlled (comes from handlers.py), unlikely to have bad data. But defensive coding would wrap this.

### 5. Template variables support only two properties

```python
ALLOWED_PROPERTIES = {"ip", "name"}
```
`template_vars.py`, line 25

Only `{{Instance.ip}}` and `{{Instance.name}}` are supported. But what if user wants `{{Instance.instance_id}}` or `{{Instance.public_ip}}`? The infrastructure exists (`build_instance_data()` could be extended), but it's not exposed.

Not a bug, just a feature limitation. Document this clearly or add more properties.

**Impact:** Low. Documented in module docstring.

### 6. S3 bucket name check is incomplete

```python
if not settings.AWS_S3_BUCKET_NAME:
    logger.error("generate_script_upload_url: AWS_S3_BUCKET_NAME not configured")
    raise S3Error("AWS_S3_BUCKET_NAME is not configured")
```
`s3.py`, lines 42-44

Checks `if not settings.AWS_S3_BUCKET_NAME` — this is True if the setting is None or empty string. But what if it's set to an invalid bucket name? The presigned URL generation would fail with a boto3 error later.

The CMS pattern (cms/assets/s3.py) does the same check, so this is consistent. But it's not truly defensive — should validate bucket name format or try to access it.

**Impact:** Low. Configuration errors surface quickly during testing.

### 7. Experiment bundle download has no implementation

```python
@staff_member_required
def experiment_download(request: HttpRequest, experiment_id: int) -> HttpResponse:
    """Redirect to presigned download URL for experiment bundle."""
    try:
        url = services.get_bundle_download_url(cast("User", request.user), experiment_id)
        return redirect(url)
    except ArtifactError as e:
        messages.error(request, str(e))
        return redirect("experiments:experiment_detail", experiment_id=experiment_id)
```
`views.py`, lines 234-242

The view exists, but `ExperimentArtifact` records are never created (artifact collection is stubbed). So this endpoint will always fail with "Experiment bundle not found."

This is intentional (feature incomplete), but should be documented or disabled in the UI until implemented.

**Impact:** Low. User sees error message, not a crash.

### 8. No cleanup of failed uploads

```python
if actual_size > max_size:
    logger.warning(...)
    delete_s3_object(s3_key)
    raise ScriptUploadError(...)
```
`services.py`, lines 142-148

If file size exceeds limit after upload, it's deleted from S3. Good.

But what if `complete_script_upload()` fails for another reason (token expired, user deleted between initiate and complete)? The uploaded file remains in S3 forever, wasting storage.

The CMS has the same issue with asset uploads. This is a known gap across the platform.

**Impact:** Low-medium. Storage leaks over time, but S3 costs are low. Add a lifecycle policy to clean up orphaned objects.

### 9. Model __str__ methods lose context in logs

```python
def __str__(self) -> str:
    return f"{self.name} ({self.status})"
```
`models.py`, line 110

When an Experiment is logged, it shows as "Test Experiment (draft)". No ID, no user. If you see this in logs, you can't look up the record without searching by name (which may not be unique).

Better: `f"Experiment(id={self.pk}, user={self.user_id}, name={self.name}, status={self.status})"`

The CMS models do this inconsistently. Some have full context, some are minimal.

**Impact:** Low. Makes debugging slightly harder.

### 10. Type hints use TYPE_CHECKING imports inconsistently

`services.py` uses:
```python
if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet
```

But then defines parameters as `user: User`. At runtime, `User` is not in scope (it's only imported inside `if TYPE_CHECKING`), but the function signature references it. Python allows this because annotations are not evaluated at runtime (unless you use `from __future__ import annotations`, which this module does at line 6).

This is correct usage, but could be clearer. Some modules use string annotations `user: "User"` to avoid the TYPE_CHECKING block.

**Impact:** None. Works correctly, just a style observation.

### 11. Handler broadcast functions log errors at DEBUG level

```python
def _broadcast_run_status(...):
    try:
        # ... channel layer operations ...
    except Exception:
        logger.debug("_broadcast_run_status: channel layer unavailable", exc_info=True)
```
`handlers.py`, lines 54-55 (and 84-85 for experiment status)

When WebSocket broadcasting fails, errors are logged at DEBUG level. This is unusual—if the channel layer is unavailable, WebSocket clients won't receive real-time updates, which is degraded functionality. Typically this would be WARNING or ERROR level.

However, this might be intentional since the channel layer is optional in development environments, and the application continues to function without WebSockets (users can refresh the page).

**Impact:** Low. Makes it harder to detect production issues where WebSockets are expected but failing silently.

### 12. No type validation on event handler payload data

```python
def _handle_range_provisioned(event: dict) -> None:
    experiment_id = event.get("experiment_id")
    run_id = event.get("run_id")

    if not experiment_id or not run_id:
        logger.warning("range_provisioned: missing experiment_id or run_id")
        return

    orchestrator = ExperimentOrchestrator(experiment_id)  # Expects int
```
`handlers.py`, lines 143-153

Handlers check for presence (`if not experiment_id`) but not type. If an event contains `experiment_id="abc"`, the check passes (non-empty string is truthy), but then `ExperimentOrchestrator(experiment_id)` fails on line 49 (`int(self.scope["url_route"]...)`) with a generic ValueError.

The CMS pattern would validate: `if not isinstance(experiment_id, int)`.

**Impact:** Low. Events come from internal systems (SQS), so malformed data is unlikely. But defensive coding would catch this at the boundary.

### 13. Template variable resolution doesn't sanitize shell metacharacters

```python
def _build_claude_command(self, resolved_prompt: str) -> str:
    escaped_prompt = resolved_prompt.replace("'", "'\\''")
    return (
        f"claude --dangerously-skip-permissions "
        f"-p '{escaped_prompt}' "
        f"2>&1 | tee /tmp/claude_output.json"
    )
```
`orchestrator.py`, lines 343-350

The function escapes single quotes, but `resolved_prompt` could contain other shell metacharacters (backticks, `$()`, `|`, `;`, etc.). Template variables are resolved from:
1. User-provided Claude prompt text (can contain anything)
2. Instance IPs and names from provisioned infrastructure (controlled by AWS)

The resolved variables themselves (IPs/names) are safe because they come from AWS provisioning. But the prompt text around them is user-controlled.

**Security boundary:** Only staff users can create experiments, and they're trusted to not inject malicious commands. The commands run in isolated ECS tasks in the user's own range, so impact is limited to self-compromise.

**Impact:** Low-Medium. Not a critical security issue given the trust model, but worth documenting that staff users have arbitrary command execution in their ranges via Claude prompts.

**Note:** This is probably intentional—users need flexibility to write complex prompts.

### 14. Orchestrator doesn't validate provisioned_instances structure

```python
def _build_execution_plan(self, run: ExperimentRun, provisioned_instances: dict[str, Any]) -> RunExecutionPlan:
    instance_data = build_instance_data(provisioned_instances)
```
`orchestrator.py`, line 287

`provisioned_instances` is passed directly to `build_instance_data()` without structure validation. If malformed, `build_instance_data()` handles it gracefully (line 116 checks `isinstance(details, dict)`), but error messages are unclear.

```python
def build_instance_data(provisioned_instances: dict[str, Any]) -> dict[str, dict[str, Any]]:
    for name, details in provisioned_instances.items():
        if isinstance(details, dict):
            result[name] = {"ip": details.get("private_ip", ""), "name": name}
        else:
            logger.warning("build_instance_data: unexpected format for instance %s", name)
            result[name] = {"ip": "", "name": name}
```
`template_vars.py`, lines 115-123

If provisioned data is completely wrong (e.g., `None` instead of dict), the orchestrator continues but generates empty IPs, which causes Claude prompts to have blank variables. The run doesn't fail cleanly.

**Impact:** Low. Provisioned data comes from the engine, which is controlled. But defensive validation at the orchestrator boundary would catch engine bugs earlier.

---

## False Positives (Things that look wrong but aren't)

### 1. Orchestrator methods that "do nothing"

```python
def _request_range_provisioning(self, run: ExperimentRun) -> None:
    logger.info(...)
    # No implementation
```

This looks like dead code, but the module docstring explains: "Actual SSM commands are dispatched via ECS tasks (portal lacks SSM permissions)." These are intentional stubs for integration points.

### 2. Scripts variable in template never used

```javascript
const scripts = {{ scripts|safe }};
```
`experiment_create.html`, line 191

Looks like it should be used by the script assignment UI, but it's not. However, this is not a bug — the script assignment UI dynamically loads scripts when needed. The variable is dead code and should be removed, but its presence doesn't break anything.

### 3. No test for S3 upload presigned URLs

Tests mock `generate_script_upload_url()` but don't verify the actual boto3 presigned URL generation. This is intentional — testing presigned URLs requires real AWS credentials or complex mocking. The CMS tests do the same.

---

## Recommendations

**Before production:**
1. Fix exception hierarchy (ExperimentError → CMSError)
2. Add user validation
3. Add catch-all exception handlers
4. Fix start_experiment race condition
5. Validate template variables at creation time
6. Add cancel confirmation

**Before wider adoption:**
7. Improve logging (debug entry, view logging)
8. Integration tests
9. WebSocket tests
10. Clean up dead code

**Long-term:**
11. Implement artifact collection
12. Add S3 cleanup lifecycle policy
13. Extend template variable properties
14. Add pagination

The experiment manager is **production-ready with moderate risk**. It's architecturally sound, follows established patterns, and has good test coverage. The gaps are refinements, not blockers. It's significantly better than the scenario editor was at initial review.

---

## Post-Review Verification (2026-02-08)

A thorough code review was conducted comparing the experiment manager implementation against:
1. CMS services.py quality standards (exception handling, logging, validation, defensive coding)
2. Architectural consistency with existing platform patterns
3. Functional correctness and user experience
4. The scenario editor baseline at initial review

### Confirmed Findings

All findings in the original review remain **accurate and valid**:

1. **Exception hierarchy gap** - ExperimentError doesn't extend CMSError (HIGH priority)
2. **Missing user validation** - No `_validate_user()` calls in services (HIGH priority)
3. **Incomplete exception handling** - Missing catch-all handlers in services and views (HIGH priority)
4. **Race condition** - `start_experiment()` can be called concurrently (HIGH priority)
5. **Inconsistent logging** - No debug entry points, minimal view logging (MEDIUM priority)
6. **Missing template validation** - Claude prompts not validated at creation time (MEDIUM priority)
7. **No cancel confirmation** - UI allows one-click cancel without prompt (MEDIUM priority)

### Additional Findings

Four minor issues discovered during verification (all LOW-MEDIUM impact):

1. **Handler broadcast errors logged at DEBUG level** - WebSocket failures hard to detect in production
2. **No type validation on event payloads** - Events checked for presence, not type
3. **Template resolution doesn't sanitize shell characters** - Low risk given trust model
4. **No structure validation on provisioned_instances** - Relies on engine data quality

### Architecture Assessment

**Excellent.** The implementation demonstrates:
- ✅ Clean separation of concerns (services ↔ views ↔ models ↔ orchestrator)
- ✅ Proper Django app integration (not external like scenario editor)
- ✅ Consistent use of established patterns (soft-delete, state machines, presigned URLs, WebSocket consumers)
- ✅ Well-designed state machine with explicit transition rules
- ✅ Good use of Pydantic for input validation
- ✅ Comprehensive test coverage at unit level

**Compared to scenario editor:** No XSS vulnerabilities, no broken JS serialization, no architectural inconsistencies, much better exception handling baseline.

### Functional Assessment

**Works correctly for implemented features.** State machine is solid, orchestration logic is sound, WebSocket real-time updates function properly. Integration points are stubbed (script execution, artifact collection) but the architecture is ready for them.

### User Experience Assessment

**Good.** Real-time status updates via WebSocket, consistent XDR dark theme, clear error messages via Django messages framework, form validation feedback. Minor rough edges (script assignment UI, no progress indicators, generic error messages).

### Risk Assessment

**Moderate risk for production use.** The code will function correctly and won't lose data or crash, but lacks the defensive rigor of mature CMS services. Key risks:

1. **Unclear error messages** - Missing user validation means TypeError from ORM instead of clear "user cannot be None"
2. **Harder debugging** - Missing catch-all exception handlers means some errors aren't logged with context
3. **Potential for confusion** - Generic error messages like "Experiment not found" don't explain why

None of these are showstoppers, but they make production debugging harder and the user experience less polished.

### Recommendation

**Ship it with the 7 HIGH-priority fixes completed.** The code is production-ready and represents significant improvement over scenario editor. The identified gaps are refinements that can be addressed in follow-up work without blocking launch.

The experiment manager demonstrates solid engineering and good understanding of Django/async patterns. With the exception hierarchy fix and defensive coding improvements, it will meet the CMS quality bar.

---

## Implementation Checklist & Task Plan

### Architectural Decision: Migrate to CMS Sub-App

The experiment manager currently lives at `shifter_platform/experiments/` as a top-level Django app. It should be migrated to `shifter_platform/cms/experiments/` as a sub-app of CMS, matching the pattern established by `cms/assets/`, `cms/scenarios/`, and `cms/scenario_editor/`.

**Rationale:**
- Experiments are content — they reference scenarios, scripts, and agents, all CMS-managed entities
- The CMS already has the exception hierarchy (`CMSError`), service patterns, and shared utilities that experiments depend on
- Sub-app structure matches how `scenario_editor/` is organized within CMS
- Keeps the CMS as the single authority for content-related domain logic

---

### Phase 0: Migration (Sequential — must complete before other phases)

This phase changes file locations and import paths. Everything else builds on top of it.

- [x] **0.1** Move `experiments/` directory to `cms/experiments/`
- [x] **0.2** Update `apps.py` name to `cms.experiments` (added `label = "experiments"` for zero-DB-change migration)
- [x] **0.3** Update all internal imports (`from experiments.X` → `from cms.experiments.X`) — 17 files
- [x] **0.4** Update `config/urls.py` to route through CMS (`cms.experiments.urls`)
- [x] **0.5** Update `config/asgi.py` WebSocket routing import
- [x] **0.6** Update `config/settings.py` INSTALLED_APPS, SQS_QUEUE_CONFIG, and LOGGING
- [x] **0.7** Update Django migration references (dependencies on `experiments` app label) — N/A, `label = "experiments"` preserves all migration/DB references
- [x] **0.8** Update all test imports — 8 test files
- [x] **0.9** Run full test suite — 1697 passed, 2 skipped, 0 failures
- [x] **0.10** Verify WebSocket routing, URL resolution, and admin registration still work — Django `check` passes, `showmigrations experiments` finds migration

**Cannot parallelize:** Each step depends on the previous. One person, sequential.

---

### Phase 1: Exception & Error Handling (Parallelizable — 3 independent tracks)

All items in this phase are independent of each other. Three people can work these simultaneously.

**Track A — Exception Hierarchy**
- [x] **1.1** Change `ExperimentError` base class to `CMSError` (`exceptions.py`)
- [x] **1.2** Verify all exception subclasses still work (`ScriptUploadError`, `ExperimentValidationError`, `ExperimentStateError`, `ArtifactError`)
- [x] **1.3** Update any `except ExperimentError` blocks that need to also handle `CMSError` propagation — N/A, no `except CMSError` blocks in experiments

**Track B — User Validation**
- [x] **1.4** Add `_validate_user()` helper to `services.py` (match CMS pattern from `cms/services.py:368-394`)
- [x] **1.5** Call `_validate_user()` at the top of every service function that takes a `user` parameter: `list_scripts`, `delete_script`, `initiate_script_upload`, `complete_script_upload`, `list_experiments`, `get_experiment`, `create_experiment`, `start_experiment`, `cancel_experiment`, `get_bundle_download_url`, `get_artifact_download_url`
- [x] **1.6** Add tests for None/invalid user parameter on key service functions

**Track C — Catch-All Exception Handlers**
- [x] **1.7** Add `except Exception` catch-all with `logger.exception()` to all service functions that don't already have one
- [x] **1.8** Add `except Exception` catch-all to all view functions — log error, show generic error message via `messages.error()`, redirect gracefully
- [x] **1.9** Update existing tests to verify error logging on unexpected exceptions

---

### Phase 2: Race Condition & State Safety (Sequential — single track)

The race condition fix touches services, models, and tests together. Best handled by one person.

- [x] **2.1** Fix `start_experiment()` race condition — moved fetch + status check inside `transaction.atomic()` with `select_for_update()` on the experiment row
- [x] **2.2** Add test for concurrent `start_experiment()` calls — `ConcurrentStartTest` uses `threading.Barrier` to race 2 threads, asserts exactly 1 succeeds and run count is not doubled
- [x] **2.3** Fix orchestrator `schedule_runs()` race condition — wrapped scheduling logic in `transaction.atomic()` with `select_for_update()` on experiment row and pending runs; `ConcurrentScheduleRunsTest` verifies max_parallel is respected
- [x] **2.4** `IntegrityError` from `unique_experiment_run_number` handled — `bulk_create` wrapped with `IntegrityError` catch as defense-in-depth, raises `ExperimentStateError("Experiment is already being started")`

**Cannot parallelize with Phase 1 Track C** if both touch the same service functions' exception handling. Schedule after or coordinate.

---

### Phase 3: Logging & Validation (Parallelizable — 2 independent tracks)

**Track D — Logging**
- [x] **3.1** Add `logger.debug()` entry point to every service function (match CMS pattern: log function name + all parameter IDs) — added to all 12 service functions after `_validate_user()`
- [x] **3.2** Add `logger.info()` / `logger.warning()` to all view functions (log HTTP method, action outcome) — added `logger.info()` entry logging to all 11 view functions
- [x] **3.3** Change handler broadcast error logging from DEBUG to WARNING (`handlers.py:54-55, 84-85`) — changed both `logger.debug` → `logger.warning`
- [x] **3.4** Change invalid state transition log level from WARNING to ERROR (`models.py:112-126`) — changed `logger.warning` → `logger.error` in both `Experiment.transition_to` and `ExperimentRun.transition_to`
- [x] **3.5** Improve `__str__` methods on models to include `pk` and `user_id` for log readability — updated `ScriptAsset`, `Experiment`, `ExperimentRun` to include pk and identifiers; updated corresponding model tests

**Track E — Validation**
- [x] **3.6** Call `template_vars.validate_template()` in `create_experiment()` — validates Claude prompt variables match scenario instances at creation time; raises `ExperimentValidationError` with specific error messages
- [x] **3.7** Add type validation to event handler payloads — extracted `_validate_event_ids()` helper; all 6 handlers use it to validate presence and `isinstance(value, int)` for `experiment_id`/`run_id`
- [x] **3.8** Add structure validation on `provisioned_instances` in orchestrator — added `isinstance(provisioned_instances, dict)` guard at top of `handle_range_provisioned()`, logs error and defaults to `{}`
- [x] **3.9** Add tests for template validation and event type validation — 3 template tests in `test_services.py` (`test_invalid_template_variable_rejected`, `test_invalid_template_property_rejected`, `test_valid_template_variable_accepted`); 2 event ID type tests in `test_handlers.py` (`test_string_experiment_id_ignored`, `test_string_run_id_ignored`); all 130 tests pass

---

#### Phase 3 Implementation Plan

##### 3.1: Debug entry logging in services

Add `logger.debug("<func_name> called with ...")` as the first line after `_validate_user()` in every service function. For `get_scenario_instances` (no user), add it as the first line of the try block.

**Files:** `cms/experiments/services.py`

Functions and their debug log format:
```python
# list_scripts (after _validate_user, line 85)
logger.debug("list_scripts called for user_id=%s", user.id)

# initiate_script_upload (after _validate_user, line 110)
logger.debug("initiate_script_upload called for user_id=%s filename=%s", user.id, filename)

# complete_script_upload (after _validate_user, line 158)
logger.debug("complete_script_upload called for user_id=%s", user.id)

# delete_script (after _validate_user, line 218)
logger.debug("delete_script called for user_id=%s script_id=%s", user.id, script_id)

# list_experiments (after _validate_user, line 250)
logger.debug("list_experiments called for user_id=%s", user.id)

# get_experiment (after _validate_user, line 282)
logger.debug("get_experiment called for user_id=%s experiment_id=%s", user.id, experiment_id)

# create_experiment (after _validate_user, line 311)
logger.debug("create_experiment called for user_id=%s scenario=%s", user.id, data.scenario_id)

# start_experiment (after _validate_user, line 404)
logger.debug("start_experiment called for user_id=%s experiment_id=%s", user.id, experiment_id)

# cancel_experiment (after _validate_user, line 459)
logger.debug("cancel_experiment called for user_id=%s experiment_id=%s", user.id, experiment_id)

# get_artifact_download_url (after _validate_user, line 498)
logger.debug("get_artifact_download_url called for user_id=%s experiment_id=%s artifact_id=%s", user.id, experiment_id, artifact_id)

# get_bundle_download_url (after _validate_user, line 537)
logger.debug("get_bundle_download_url called for user_id=%s experiment_id=%s", user.id, experiment_id)

# get_scenario_instances (first line of try block, line 581)
logger.debug("get_scenario_instances called for scenario_id=%s", scenario_id)
```

##### 3.2: View-level logging

Add `logger.info()` on successful operations and `logger.warning()` on expected failures to each view function. The services layer already logs, but view logging adds HTTP context (which endpoint, which action).

**Files:** `cms/experiments/views.py`

Pattern — add after successful service call:
```python
# script_list (after render, around line 44)
logger.info("script_list: user_id=%s", request.user.id)

# script_upload GET (line 69)
logger.debug("script_upload: GET user_id=%s", request.user.id)

# script_upload POST completion success (after line 79)
logger.info("script_upload: completed user_id=%s script=%s", request.user.id, script.name)

# script_upload POST completion failure (after line 81)
logger.warning("script_upload: completion failed user_id=%s: %s", request.user.id, e)

# script_upload POST initiate success (after line 97)
logger.info("script_upload: initiated user_id=%s", request.user.id)

# script_upload POST initiate failure (after line 98)
logger.warning("script_upload: initiate failed user_id=%s: %s", request.user.id, e)

# script_delete success (after line 117)
logger.info("script_delete: user_id=%s script_id=%s", request.user.id, script_id)

# script_delete failure (after line 118)
logger.warning("script_delete: failed user_id=%s script_id=%s: %s", request.user.id, script_id, e)

# experiment_list success (line 138)
logger.info("experiment_list: user_id=%s", request.user.id)

# experiment_create POST success (after line 206)
logger.info("experiment_create: user_id=%s experiment_id=%s", request.user.id, experiment.pk)

# experiment_create POST validation failure (after line 208)
logger.warning("experiment_create: validation failed user_id=%s: %s", request.user.id, e)

# experiment_detail success (after line 226)
logger.info("experiment_detail: user_id=%s experiment_id=%s", request.user.id, experiment_id)

# experiment_start success (after line 253)
logger.info("experiment_start: user_id=%s experiment_id=%s", request.user.id, experiment_id)

# experiment_start failure (after line 255-258)
logger.warning("experiment_start: failed user_id=%s experiment_id=%s: %s", request.user.id, experiment_id, e)

# experiment_cancel success (after line 273)
logger.info("experiment_cancel: user_id=%s experiment_id=%s", request.user.id, experiment_id)

# experiment_cancel failure (after line 275)
logger.warning("experiment_cancel: failed user_id=%s experiment_id=%s: %s", request.user.id, experiment_id, e)

# experiment_download success (after line 295)
logger.info("experiment_download: user_id=%s experiment_id=%s", request.user.id, experiment_id)

# artifact_download success (after line 318)
logger.info("artifact_download: user_id=%s experiment_id=%s artifact_id=%s", request.user.id, experiment_id, artifact_id)

# scenario_instances success (after line 341)
logger.debug("scenario_instances: scenario_id=%s", scenario_id)
```

##### 3.3: Handler broadcast log levels

Change two lines in `handlers.py`:

```python
# Line 55: DEBUG -> WARNING
logger.warning("_broadcast_run_status: channel layer unavailable", exc_info=True)

# Line 85: DEBUG -> WARNING
logger.warning("_broadcast_experiment_status: channel layer unavailable", exc_info=True)
```

##### 3.4: Invalid transition log level

Change `logger.warning` to `logger.error` in both transition methods:

```python
# models.py line 125 (Experiment.transition_to):
logger.error("Experiment %s: %s", self.pk, msg)

# models.py lines 267-272 (ExperimentRun.transition_to):
logger.error(
    "ExperimentRun %s (experiment=%s): %s",
    self.pk,
    self.experiment_id,
    msg,
)
```

##### 3.5: Model `__str__` improvements

```python
# Experiment.__str__ (models.py:109-110):
def __str__(self) -> str:
    return f"Experiment(id={self.pk}, name={self.name}, status={self.status})"

# ExperimentRun.__str__ (models.py:251-252):
def __str__(self) -> str:
    return f"Run(id={self.pk}, experiment={self.experiment_id}, num={self.run_number}, status={self.status})"

# ExperimentScript.__str__ (models.py:193-194) — no change needed (already has instance_name and type, no pk/user needed for script bindings)

# ScriptAsset.__str__ (models.py:54-55):
def __str__(self) -> str:
    return f"ScriptAsset(id={self.pk}, name={self.name}, file={self.original_filename})"
```

##### 3.6: Template variable validation at creation time

In `services.py` `create_experiment()`, after the instance name validation loop (line 326), add validation for Claude prompts:

```python
        # Validate Claude prompt template variables reference valid instances
        for script_input in data.scripts:
            if script_input.script_type.value == "claude_code" and script_input.claude_prompt:
                from cms.experiments.template_vars import validate_template

                errors = validate_template(script_input.claude_prompt, instance_names)
                if errors:
                    raise ExperimentValidationError(
                        f"Invalid template variable in prompt for '{script_input.instance_name}': {'; '.join(errors)}"
                    )
```

Import note: `validate_template` is a lightweight function, inline import is fine to avoid circular import risk.

##### 3.7: Type validation on event handler payloads

In `handlers.py`, each handler checks `if not experiment_id` for presence. Add `isinstance` checks after the presence checks:

```python
# _handle_experiment_start (line 131-134):
def _handle_experiment_start(event: dict) -> None:
    experiment_id = event.get("experiment_id")
    if not experiment_id:
        logger.warning("experiment.start: missing experiment_id")
        return
    if not isinstance(experiment_id, int):
        logger.warning("experiment.start: experiment_id is not int: %s", type(experiment_id).__name__)
        return
```

Same pattern for all 6 handlers that read `experiment_id` and/or `run_id`:
- `_handle_experiment_start`: validate `experiment_id`
- `_handle_range_provisioned`: validate `experiment_id`, `run_id`
- `_handle_victim_scripts_completed`: validate `experiment_id`, `run_id`
- `_handle_attacker_scripts_completed`: validate `experiment_id`, `run_id`
- `_handle_artifacts_collected`: validate `experiment_id`, `run_id`
- `_handle_run_failed`: validate `experiment_id`, `run_id`

To avoid repeating the validation in each handler, extract a helper:

```python
def _validate_event_ids(event: dict, handler_name: str, *fields: str) -> dict | None:
    """Extract and validate required integer fields from event dict.

    Returns dict of field->value if valid, or None if validation fails.
    """
    result = {}
    for field in fields:
        value = event.get(field)
        if not value:
            logger.warning("%s: missing %s", handler_name, field)
            return None
        if not isinstance(value, int):
            logger.warning("%s: %s is not int: %s", handler_name, field, type(value).__name__)
            return None
        result[field] = value
    return result
```

Then each handler becomes:
```python
def _handle_experiment_start(event: dict) -> None:
    ids = _validate_event_ids(event, "experiment.start", "experiment_id")
    if ids is None:
        return
    orchestrator = ExperimentOrchestrator(ids["experiment_id"])
    ...
```

##### 3.8: Structure validation on provisioned_instances

In `orchestrator.py` `handle_range_provisioned()`, validate the input before using it:

```python
def handle_range_provisioned(self, run_id: int, provisioned_instances: dict[str, Any]) -> None:
    # Validate provisioned_instances structure
    if not isinstance(provisioned_instances, dict):
        logger.error(
            "handle_range_provisioned: provisioned_instances is not a dict (type=%s) for run %s",
            type(provisioned_instances).__name__,
            run_id,
        )
        provisioned_instances = {}
    ...
```

This ensures that even if the engine sends malformed data, the orchestrator logs the issue clearly and degrades gracefully (empty dict means no instance_ids matched, scripts get skipped with existing warnings).

##### 3.9: Tests for template validation at creation time

Add to `test_services.py` in the existing `CreateExperimentTest` class:

```python
def test_invalid_template_variable_rejected(self):
    """Claude prompts with unknown instance names are rejected at creation time."""
    data = ExperimentCreateInput(
        name="Bad Template",
        scenario_id="basic",
        scripts=[
            {
                "instance_name": "Attacker",
                "script_type": "claude_code",
                "claude_prompt": "Attack {{NonExistent.ip}}",
                "execution_order": 100,
            }
        ],
    )
    with pytest.raises(ExperimentValidationError, match="Unknown instance"):
        services.create_experiment(self.user, data)

def test_invalid_template_property_rejected(self):
    """Claude prompts with unknown properties are rejected at creation time."""
    data = ExperimentCreateInput(
        name="Bad Property",
        scenario_id="basic",
        scripts=[
            {
                "instance_name": "Attacker",
                "script_type": "claude_code",
                "claude_prompt": "Get {{Workstation.hostname}}",
                "execution_order": 100,
            }
        ],
    )
    with pytest.raises(ExperimentValidationError, match="Unknown property"):
        services.create_experiment(self.user, data)

def test_valid_template_variable_accepted(self):
    """Claude prompts with valid variables pass creation validation."""
    data = ExperimentCreateInput(
        name="Good Template",
        scenario_id="basic",
        scripts=[
            {
                "instance_name": "Attacker",
                "script_type": "claude_code",
                "claude_prompt": "Attack {{Workstation.ip}}",
                "execution_order": 100,
            }
        ],
    )
    exp = services.create_experiment(self.user, data)
    assert exp.pk is not None
```

Add to `test_handlers.py`:

```python
class EventIdValidationTest(TestCase):
    def test_string_experiment_id_ignored(self):
        """Handler ignores event with non-integer experiment_id."""
        from cms.experiments.handlers import process_event
        # Should not raise — just log warning and skip
        process_event({"event_type": "experiment.start", "experiment_id": "abc"})

    def test_string_run_id_ignored(self):
        """Handler ignores event with non-integer run_id."""
        from cms.experiments.handlers import process_event
        process_event({
            "event_type": "experiment.run.failed",
            "experiment_id": 1,
            "run_id": "not-an-int",
        })
```

#### Verification

1. Run experiment tests:
   ```
   cd shifter/shifter_platform && source .venv/bin/activate && TESTING=1 python -m pytest cms/experiments/tests/ -v
   ```

2. Run full suite:
   ```
   TESTING=1 python -m pytest --tb=short
   ```

---

### Phase 4: UX & Cleanup (Parallelizable — all independent)

These are small, isolated changes. Can be done by anyone with spare capacity.

- [x] **4.1** Add `onclick="return confirm('Cancel this experiment?')"` to cancel button in `experiment_detail.html` — added with "This cannot be undone." text
- [x] **4.2** Remove dead `scripts` variable from `experiment_create.html` template — removed JS variable and the unused `scripts` context variable from the view
- [x] **4.3** Improve error messages — changed "not found" → "not found or you don't have access" for Experiment, Script, Artifact, and Bundle errors in `services.py`
- [x] **4.4** Improve Pydantic validation error display — added specific `PydanticValidationError` catch in `experiment_create` view; extracts field-level `loc`/`msg` pairs for readable output
- [x] **4.5** Show "Runs will be created when experiment starts" in empty runs table during DRAFT state — added `{% elif experiment.status == "draft" %}` block with message

---

### Phase 5: Test Coverage (Parallelizable — 3 independent tracks)

Run after Phases 1-4 are complete so tests cover the fixed code.

**Track F — Integration Tests**
- [x] **5.1** Write end-to-end test: create experiment → start → verify runs created → simulate orchestrator flow → verify completion — `ExperimentLifecycleTest` in `test_integration.py` with 3 tests: `test_full_lifecycle` (create→start→schedule→complete all runs→experiment completes), `test_lifecycle_with_failure` (one run fails, one succeeds, experiment still completes), `test_cancel_stops_experiment` (cancel prevents scheduling)
- [x] **5.2** Write end-to-end test: script upload → assign to experiment → verify linkage — `ScriptAssignmentIntegrationTest` in `test_integration.py` with 3 tests: `test_script_assigned_to_experiment` (Python + Claude script linkage verified), `test_deleted_script_not_assignable` (soft-deleted script rejected), `test_initiate_upload_returns_presigned_data` (mocked S3 upload initiation)

**Track G — WebSocket Tests**
- [x] **5.3** Test consumer authentication (reject unauthenticated, reject non-owner) — `TestConsumerAuthentication` in `test_consumers.py` with 5 tests: anonymous (4001), no_user (4001), non_staff (4003), non_owner (4004), owner accepted; uses `WebsocketCommunicator` + `database_sync_to_async`
- [x] **5.4** Test hydration on connect (initial state sent correctly) — `TestConsumerHydration` in `test_consumers.py` with 2 tests: hydrate with runs (verifies experiment_status, run statuses, run ordering), hydrate empty (verifies empty runs list)
- [x] **5.5** Test broadcast reception (run status updates delivered to connected clients) — `TestConsumerBroadcast` in `test_consumers.py` with 2 tests: `test_receives_run_status_broadcast` (run_status event delivered), `test_receives_experiment_status_broadcast` (experiment_status event delivered); consumer coverage reached 100%

**Track H — Edge Case Tests**
- [x] **5.6** Test race condition on `start_experiment` (threading) — covered in Phase 2 (`ConcurrentStartTest` in `test_services.py`)
- [x] **5.7** Test template with invalid variables rejected at creation — covered in Phase 3 (3.9: `test_invalid_template_variable_rejected`, `test_invalid_template_property_rejected`, `test_valid_template_variable_accepted` in `test_services.py`)
- [x] **5.8** Test malformed JSON in `scripts_json` POST field — `MalformedInputViewTest` in `test_views.py` with 3 tests: `test_malformed_scripts_json_shows_error` (invalid JSON → 302 not 500), `test_empty_name_shows_validation_error` (Pydantic error → 302), `test_parallel_exceeds_total_shows_error` (max_parallel > total → 302)
- [x] **5.9** Test event handler with wrong types (string experiment_id, missing fields) — covered in Phase 3 (3.9: `test_string_experiment_id_ignored`, `test_string_run_id_ignored` in `test_handlers.py`)

---

### Phase 6: Low Priority / Future (No urgency — backlog)

- [x] **6.1** Add response type validation (isinstance checks on ORM returns, match CMS pattern) — added `_check_result_type()` helper to `services.py`; called after every `.get()` ORM call in `get_experiment`, `start_experiment`, `cancel_experiment`, `delete_script`, `get_artifact_download_url`, `get_bundle_download_url`, and `create_experiment` (AgentConfig); raises `TypeError` with function name and expected/actual types
- [x] **6.2** Call `model.full_clean()` before save in service functions — refactored `Experiment.objects.create()` → `Experiment()` + `full_clean()` + `save()` in `create_experiment`; same for `ExperimentScript` and `ScriptAsset` in `complete_script_upload`; `DjangoValidationError` caught and converted to domain errors (`ExperimentValidationError` / `ScriptUploadError`)
- [x] **6.3** Add progress indicator on script upload (JS upload percentage) — replaced S3 `fetch()` with `XMLHttpRequest` in `script_upload.html` for `upload.onprogress` support; shows real-time upload percentage (0-100%) during S3 PUT; progress bar interpolates 30-70% during upload phase
- [x] **6.4** Improve script assignment UI (validation on blur) — added `validatePrompt()` JS function in `experiment_create.html`; validates Claude prompt template variables on blur: checks instance names against loaded scenario instances, validates property names against allowed list (ip, name, instance_id); highlights invalid fields with red border and shows errors in tooltip
- [x] **6.5** Add pagination to experiment list view — added `Paginator` (25 per page) in `experiment_list` view; template shows prev/next navigation when multiple pages exist; styled consistent with XDR theme
- [ ] **6.6** Implement artifact collection (`_collect_artifacts()` stub) — requires ECS task runner integration (portal lacks SSM permissions); cannot implement without infrastructure details
- [ ] **6.7** Implement command dispatch (`_dispatch_commands()` stub) — requires ECS task runner integration; depends on task definition, SNS topics, and SSM document configuration
- [ ] **6.8** Implement range provisioning request (`_request_range_provisioning()` stub) — requires engine provisioning API integration; depends on CMS→Engine communication pattern
- [ ] **6.9** Add S3 lifecycle policy for orphaned upload cleanup — AWS infrastructure configuration (Terraform/console), not application code
- [x] **6.10** Extend `ALLOWED_PROPERTIES` in `template_vars.py` beyond `{ip, name}` — added `instance_id` property; updated `ALLOWED_PROPERTIES`, `build_instance_data()` to include `instance_id` from provisioned data, module docstring; added 2 tests (`test_instance_id_property_valid`, `test_resolves_instance_id`) and updated existing assertions
- [x] **6.11** Sanitize shell metacharacters in resolved prompts (or document the trust model) — added docstring to `_build_claude_command()` in `orchestrator.py` documenting the security boundary: only staff users can create experiments, commands execute in isolated ECS tasks within user's own range, and users need flexibility for complex prompts

---

### Parallelization Summary

```
Phase 0 (Migration)          ████████████████  [1 person, sequential]
                                              |
                              ┌───────────────┼───────────────┐
Phase 1A (Exceptions)         ████             |               |
Phase 1B (User Validation)    |    ████████    |               |
Phase 1C (Catch-All Handlers) |         ████████               |
                              └───────────────┼───────────────┘
                                              |
Phase 2 (Race Condition)                 ██████  [1 person, after Phase 1C]
                                              |
                              ┌───────────────┴───────────────┐
Phase 3D (Logging)            ████████████                     |
Phase 3E (Validation)         |    ████████████                |
                              └───────────────┬───────────────┘
                                              |
Phase 4 (UX & Cleanup)       ████████████████  [anyone, parallel tasks]
                                              |
                              ┌───────────────┼───────────────┐
Phase 5F (Integration Tests)  ████████████     |               |
Phase 5G (WebSocket Tests)    |    ████████    |               |
Phase 5H (Edge Case Tests)   |         ████████               |
                              └───────────────┴───────────────┘
```

**Maximum parallelism:** 3 people after Phase 0
**Critical path:** Phase 0 → Phase 1C → Phase 2 → Phase 5H
**Total independent work items:** 50 checklist items across 11 tracks
