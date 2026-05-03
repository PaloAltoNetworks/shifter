# Scenario Editor Code Review

## Critical Bugs (will break in production)

### 1. Form editor JS is broken for existing scenarios

```
let instances = {{ scenario.instances|safe|default:"[]" }};
```
`form.html`, line 126

When editing an existing scenario, `scenario.instances` is a Python list. Django's `{{ |safe }}` calls `str()` on it, producing Python repr syntax: `[{'name': 'Attacker', 'xdr_agent': False, 'dc_config': None}]`. That is not valid JavaScript. Python's `False` -> JS needs `true`/`false`; Python's `None` -> JS needs `null`; Python's single-quoted strings are technically valid in JS but the bools will crash.

This means:
- The form editor **will not load** when editing any existing scenario
- The form editor **will not re-render** after a validation error on create (because the view passes back Python-parsed data)
- Only the initial GET for a brand-new create form works (because `scenario` is `None` and the `|default:"[]"` kicks in)

Fix: the view should `json.dumps()` the instances/subnets and pass them as separate context variables, or use Django's `json_script` template tag.

### 2. XSS in client-side YAML validation

In both `yaml_editor.html` and `yaml_create.html`:

```javascript
resultDiv.innerHTML = '<strong>Validation errors:</strong><ul style="margin: 4px 0 0 16px;">' +
    data.errors.map(e => `<li>${e}</li>`).join('') + '</ul>';
```

Validation errors from Pydantic include YAML field names (which come from user input). A crafted YAML with `<script>alert(1)</script>` as a key name would be rendered as HTML. This is exploitable XSS through `innerHTML` with unsanitized data. Should use `textContent` or proper escaping.

---

## Exception Handling (significant gap)

The CMS uses `CMSError` from `shared.exceptions`, part of a shared hierarchy (`CMSError`, `AssetError`, `ProvisioningError`, `ValidationError`). The scenario editor defines its own standalone exception:

```python
class ScenarioEditorError(Exception):
    """Error raised by scenario editor operations."""
```
`services.py`, lines 26-27

This doesn't extend `CMSError`. Any shared error-handling middleware or generic `except CMSError` patterns elsewhere won't catch scenario editor errors. Since the scenario editor is calling into CMS models and registry functions, having a disconnected exception hierarchy is an inconsistency.

The service layer also doesn't catch unexpected exceptions. If the database throws an `IntegrityError` (e.g., race condition on the unique constraint), it would propagate as a raw Django exception rather than being wrapped in a domain error.

---

## Logging (major gap)

The CMS services.py follows a strict pattern: `logger.debug()` at entry, `logger.error()` before raising, `logger.info()` on success, `logger.exception()` for unexpected errors. The scenario editor is significantly behind this bar:

**Services**: Has `logger.info()` after successful create/update/delete/metadata — that's good. But:
- No `logger.debug()` entry points on any function
- No `logger.error()` before raising any `ScenarioEditorError`
- No `logger.exception()` for unexpected errors
- `validate_definition()`, `validate_yaml()`, `export_scenario_yaml()`, and `clone_scenario()` have zero logging

**Views** (`views.py`, 670 lines): Despite importing `logging` and creating a logger, it is never used. Not a single log statement. When a form submission fails, or a scenario is deleted, or a toggle is flipped — nothing is logged.

**API views** (`api_views.py`, 350 lines): Same — `logger` is imported and never used.

Compare to `cms/services.py` where every function has structured debug/info/error logging with context like user_id, agent_id, etc.

---

## Validation & Defensive Coding (significant gap)

The CMS services enforce a rigorous input validation pattern at the top of every function:

```python
if user is None:
    logger.error("create_agent called with None user")
    raise TypeError(USER_CANNOT_BE_NONE)
if not hasattr(user, "id"):
    raise TypeError(f"user must be a User instance, got {type(user).__name__}")
if user.id is None:
    raise ValueError(USER_MUST_BE_SAVED)
```

The scenario editor service functions (`create_scenario`, `update_scenario`, `delete_scenario`, `clone_scenario`, `update_metadata`) accept a `user` parameter but perform zero validation on it. If `None` is passed, it would fail with an opaque `AttributeError` instead of a clear error message.

Other gaps vs the CMS:
- No `full_clean()` before `scenario.save()` — if the model has validation logic, it's skipped
- No response type validation after operations (CMS checks `isinstance(agent, AgentConfig)` on returns)
- No constants for error messages (CMS uses `USER_CANNOT_BE_NONE`, etc.)

The Pydantic-based definition validation and the DRF serializer validation are both solid and consistent with the CMS approach.

---

## Architectural Consistency

**Good:**
- Service layer pattern (services.py as the business logic boundary) matches CMS
- Soft-delete pattern (`deleted_at__isnull=True` filtering) is consistent
- Pydantic for definition validation matches `cms/scenarios/schema.py`
- `<slug:scenario_id>` URL patterns are appropriate
- Permission checking (`@login_required` + `@user_passes_test` for views, `IsStaffUser` for API) is correct
- CSRF protection on all forms and API calls
- Integration with the CMS registry (`list_all_scenarios`, `get_scenario_detail`, `is_default_scenario`) is clean

**Questionable:**
- Separate Django app (`scenario_editor/`) rather than a CMS submodule. The CMS uses `cms/assets/` and `cms/scenarios/` as submodules, and the scenario editor is tightly coupled to CMS models. Having it outside creates an unusual dependency direction.
- Dual interface (template views + DRF API views) is novel for this codebase. The CMS exposes only a Python service interface, not HTTP. Whether both interfaces are needed is worth considering — if the template views are the primary UI, the API endpoints may be premature.
- Test fixtures are duplicated across all 5 test files instead of using a shared `conftest.py`.

---

## Will It Actually Work? (functional assessment)

Aside from the critical JS bug in the form editor:

- **YAML editor flow**: Works. Textarea input -> POST -> `validate_yaml` -> `update_scenario` -> redirect. The tab-key handling and client-side validation-before-save are nice.
- **YAML create flow**: Works. Template YAML seeded for new users.
- **Clone flow**: Works. Delegates to `create_scenario`, so all validation applies.
- **Delete flow**: Works. Soft-delete + metadata cleanup.
- **Toggle flow**: Works. TOCTOU race on concurrent toggles, but acceptable for an admin tool.
- **Export flow**: Works. Returns `Content-Disposition` attachment.
- **Subtle YAML editor issue**: If a user changes the `id:` field in the YAML when editing, it's silently ignored — `update_scenario` uses the URL's `scenario_id`, not the one from the parsed YAML. No warning is shown.

---

## UX Assessment

**Good:**
- Consistent XDR dark theme styling
- Disabled scenarios at 50% opacity in the list — clear visual signal
- Inline status/access toggle buttons on both list and detail views
- YAML editor with Tab key support and client-side validation button
- Clone form pre-fills suggested ID (`{source}-copy`) and name (`Copy of {source}`)
- Delete has `confirm()` dialog
- Errors displayed in styled error lists above forms, with form data preserved on re-render

**Missing:**
- No success/flash messages after any operation. User creates a scenario and is silently redirected to the detail page — no confirmation that it worked.
- No loading indicators on form submissions
- No breadcrumb navigation
- Error pages (`error.html`, `not_found.html`) are minimal — just a message and a back link, no context about what went wrong or what to do next

---

## Summary

| Area | Rating | Notes |
|------|--------|-------|
| Exception handling | Below bar | Disconnected exception hierarchy, no unexpected-error wrapping |
| Logging | Well below bar | Views and API have zero logging; services missing debug/error/exception |
| Validation | Below bar | No user parameter validation; no `full_clean()` |
| Defensive coding | Below bar | Missing the input validation rigor seen in CMS services |
| Functional correctness | Broken | Form editor JS fails on Python->JS serialization; XSS in validation UI |
| Architecture | Mostly consistent | Separate app is unusual; dual interface may be premature |
| UX | Decent | Good styling; missing feedback/flash messages |

The YAML editor and YAML create paths would work. The form-based editor path is broken. The code needs the JS serialization fix, the XSS fix, and a pass to bring logging, exception handling, and input validation up to the standard set by the rest of the CMS.

---

## Additional Findings

### 3. XSS in form.html instance rendering (second vector)

Beyond the `|safe` serialization bug (#1), the form.html JavaScript renders instance data via `innerHTML` with template literals:

```javascript
card.innerHTML = `
    ...
    <input type="text" class="form-input" value="${inst.name || ''}" ...>
    ...
`;
```
`form.html`, line 139-191

If an instance name contained HTML like `"><img onerror=alert(1)>`, it would execute. This is a separate XSS vector from the `|safe` issue — even if the Python→JS serialization were fixed with `json_script`, injecting user data into `innerHTML` via template literals remains unsafe. Should use DOM APIs (`createElement`, `textContent`) or a sanitization step.

### 4. Empty scenario_id from YAML create path

```python
scenario_id = parsed.get("id", "")
```
`views.py`, line 473

If the YAML content omits the `id:` field, `scenario_id` will be an empty string `""`. This passes to `create_scenario`, which checks `is_default_scenario("")` (false) and `Scenario.objects.filter(scenario_id="", deleted_at__isnull=True).exists()` (false for the first one), then creates a Scenario with `scenario_id=""`. The API path prevents this via `ScenarioCreateSerializer` requiring `SlugField`, but the template path has no such guard.

Same issue for `name` and `description` — `parsed.get("name", "")` will silently pass empty strings.

### 5. Race condition on create — unhandled IntegrityError

`create_scenario` at lines 116-120:

```python
if Scenario.objects.filter(scenario_id=scenario_id, deleted_at__isnull=True).exists():
    raise ScenarioEditorError(...)
# ... gap here ...
scenario.save()  # line 141
```

Two concurrent requests can both pass the `.exists()` check. One will succeed; the other will hit the DB `unique_active_scenario_id` constraint and raise `IntegrityError`. This is unhandled — neither the service nor the views catch `IntegrityError`, so the user sees a raw 500. Should wrap in `transaction.atomic()` and catch `IntegrityError`, or use `get_or_create`.

### 6. No catch-all exception handling in views

Every template view only catches `ScenarioEditorError` and `ValueError`. Any other exception type (e.g., `IntegrityError`, `PydanticValidationError` escaping the service layer, `TypeError`, database connection errors) will propagate as an unhandled 500 with a Django debug/error page.

Example in `scenario_detail_view` (line 83): `export_scenario_yaml()` is called outside any try/except. If the scenario's definition is corrupt and causes an error during YAML serialization, the user gets a raw 500.

The CMS pattern wraps calls in `except Exception: logger.exception(...)` to ensure graceful degradation.

### 7. `save()` without `update_fields` in update paths

`update_scenario` (line 208) and `create_scenario` (line 141) call bare `scenario.save()`. `update_metadata` (line 304) calls bare `metadata.save()`. The CMS pattern uses explicit `update_fields` for updates to minimize blast radius and avoid overwriting concurrent changes. `delete_scenario` (line 245) does this correctly — the other save calls are inconsistent.

For `update_scenario` specifically, a bare `save()` writes every field, so a concurrent edit could overwrite changes. With `update_fields`, only the intended fields are written.

### 8. Form views bypass serializer validation

The API path validates input through DRF serializers (`ScenarioCreateSerializer` enforces `SlugField`, `InstanceConfigSerializer` validates `role` choices and `os_type` choices, etc.). The form views do their own weaker validation:

```python
scenario_id = request.POST.get("scenario_id", "").strip()
# ... only checks "not empty"
```
`views.py`, lines 117-145

This means the form path accepts:
- `scenario_id` values with uppercase, spaces, or special characters (serializer enforces slug format)
- Instance data with invalid `role` or `os_type` values (serializer enforces choices)
- No `max_length` enforcement on any field

The Pydantic validation in the service layer will catch structural issues, but not format constraints.

### 9. Standalone base.html diverges from site navigation

```html
{% include "partials/icon_sidebar.html" %}
<div class="layout">
    <main class="main">
        {% block content %}{% endblock %}
    </main>
</div>
```
`base.html`, lines 17-23

The scenario editor creates its own HTML document structure rather than extending the site-wide base template. If the main site changes its navigation, header, footer, or adds analytics/monitoring scripts, the scenario editor won't pick up those changes. Every other app in the project should be checked to confirm whether they extend a shared base or also roll their own.

### 10. Duplicated CSS across templates

The following CSS blocks are copy-pasted across multiple templates:
- `.form-group`, `.form-input`, `.form-textarea`, `.form-select` — duplicated in `form.html`, `clone.html`
- `.error-list` — duplicated in `form.html`, `clone.html`, `yaml_editor.html`, `yaml_create.html`
- `.yaml-editor`, `.validation-result`, `.validation-valid`, `.validation-invalid` — duplicated in `yaml_editor.html`, `yaml_create.html`

Should be extracted to a shared CSS file or a `{% block extra_css %}` in the base template.

### 11. No confirmation on toggle actions

Clicking the "Enabled" or "Staff Only" toggle buttons on the list page (lines 59-64, 67-72) immediately submits a POST form and redirects. No `confirm()` dialog, no undo. A single misclick can disable a scenario for all users or restrict it to staff-only. Delete has a `confirm()` dialog, but toggles do not.

### 12. Delete confirmation is JS-only

```html
onsubmit="return confirm('Delete this scenario?');"
```
`detail.html`, line 32

If JavaScript is disabled or fails to load, the form submits without any confirmation. The CMS pattern for destructive actions should include server-side confirmation (e.g., a dedicated confirmation page, or requiring a specific POST field).

### 13. No pagination or search on scenario list

`scenario_list` (views.py line 51) calls `list_all_scenarios(user=None)` and passes the entire list to the template. No pagination, no search, no filtering. If the number of scenarios grows, the page will become unwieldy. The CMS should be checked for how other list views handle this.

### 14. Form submit with broken JS silently sends empty data

The form relies on a JavaScript `submit` event handler (form.html line 277) to serialize instance/subnet data into hidden fields before POST:

```javascript
document.getElementById('scenarioForm').addEventListener('submit', function() {
    document.getElementById('instances_json').value = JSON.stringify(instances);
    document.getElementById('subnets_json').value = JSON.stringify(subnets);
});
```

If the JS fails (the Python→JS serialization bug in #1 would cause this), the hidden fields remain empty strings. The view reads them with:
```python
instances_json = request.POST.get("instances_json", "[]")
```

An empty string `""` is not `None`, so the default `"[]"` is not used. `json.loads("")` raises `JSONDecodeError`, which is caught and adds "Invalid instances JSON" — so the user gets an error, but the error message is misleading (it's not invalid JSON, the JS failed). This is a symptom of bug #1 but worth noting as an independent failure mode.

### 15. Redundant validation in update path

`update_scenario` (lines 197-205) explicitly calls `validate_definition()` and raises `ScenarioEditorError` if invalid. Then `scenario.save()` (line 208) triggers the model's `save()` override which calls `self.validate_definition()` → `self.to_template()`, running Pydantic validation a second time. Not harmful, but wasteful — and if the two validation paths ever diverge (e.g., the model adds constraints), the error type would differ (service raises `ScenarioEditorError`, model raises `PydanticValidationError`), causing an unhandled exception.

### 16. YAML `enabled` field is exported but ignored on import/edit

`export_scenario_yaml()` includes `enabled` in output:

```python
"enabled": data.get("enabled", True),
```
`services.py`, line 398

But both YAML save paths drop that field when building `definition`:

```python
definition = {
    "instances": parsed.get("instances", []),
    "subnets": parsed.get("subnets", []),
    "ngfw": parsed.get("ngfw", False),
}
```
`views.py`, lines 388-392 and 476-480; `api_views.py`, lines 326-330

So a user can edit `enabled:` in YAML, submit successfully, and see no change. This is a UX/behavior mismatch: the editor presents `enabled` as if editable through YAML, but the backend ignores it.

### 17. Non-slug scenario IDs can be created via YAML/API paths

The service layer does not validate `scenario_id` format before save:

```python
def create_scenario(..., scenario_id: str, ...):
    ...
    scenario = Scenario(scenario_id=scenario_id, ...)
    scenario.save()
```
`services.py`, lines 88-141

`Scenario.save()` does not call `full_clean()`, so model `SlugField` validation is not enforced at save time (`cms/models.py`, lines 774-778).

The form view has a front-end pattern check, but YAML create/import paths take `id` from parsed YAML and pass it directly to `create_scenario` (`views.py`, line 473; `api_views.py`, line 323). A non-slug ID (e.g., containing spaces) can be persisted.

Impact: URL routes use `<slug:scenario_id>` (`urls.py`, lines 21 and 31) and templates reverse scenario URLs per row (`list.html`, line 36). Invalid IDs can become unreachable via routed URLs and may break page rendering during URL reversing.

### 18. API contract/status behavior is inconsistent

- `scenario_detail` returns 404 for missing scenario (`api_views.py`, lines 107-111)
- `scenario_export_yaml` returns 400 for missing scenario (`api_views.py`, lines 290-294)
- Most other service-origin errors also return 400 regardless of not-found vs conflict vs forbidden

Template views also return HTTP 200 for several error pages (for example, default-scenario edit/delete restrictions render `error.html` without non-200 status in `views.py`, lines 206-213 and 516-522).

Result: clients and users get inconsistent semantics for equivalent failure classes.

### 19. Coverage gap: YAML import/validate API paths are untested

`tests/scenario_editor/test_api.py` has coverage for create/update/delete/clone/export/metadata, but no tests for:

- `POST /scenario-editor/api/validate-yaml/`
- `POST /scenario-editor/api/import-yaml/`

There are also no tests that exercise the form editor JS bootstrap behavior where Python data is embedded into JavaScript (`form.html`, lines 126-127), which allowed bug #1 to slip through.

---

## Fix Checklist

### Critical (broken / security)

- [x] **#1** Fix Python->JS serialization in form.html — used `json_script` template tag + `JSON.parse()`
- [x] **#2** Fix XSS in YAML validation error display — replaced `innerHTML` with DOM API (`createElement`/`textContent`)
- [x] **#3** Fix XSS in form.html instance/subnet rendering — added `escapeHtml()` utility, applied to all template literals
- [x] **#17** Validate scenario_id format in service layer — added `_SCENARIO_ID_RE` regex, checked in `create_scenario`

### High (will cause 500s or data issues)

- [x] **#5** Handle `IntegrityError` in `create_scenario` — wrapped in `transaction.atomic()` + `IntegrityError` catch
- [x] **#6** Add catch-all exception handling in all views — `except Exception: logger.exception(...)` on every view/API endpoint
- [x] **#4** Validate `scenario_id`, `name`, `description` are non-empty in YAML create/import view paths
- [x] **#15** Catch `PydanticValidationError` from model `save()` — caught and re-raised as `ScenarioEditorError`

### Medium (below CMS bar)

- [x] **Logging** Add structured logging to views.py — `logger.info()` on success, `logger.warning()` on 404, `logger.exception()` in catch-all
- [x] **Logging** Add structured logging to api_views.py — same pattern
- [x] **Logging** Add debug entry/exit and error logging to all service functions
- [x] **Logging** Add warning-level logging in `validate_definition` and `validate_yaml` on failure
- [x] **Exception hierarchy** `ScenarioEditorError` now extends `CMSError`
- [x] **Input validation** Added `_validate_user()` helper matching CMS pattern (None, type, saved checks) — called in all service functions
- [x] **#8** Form views: added slug format validation via `SLUG_RE` in `scenario_create_form`
- [x] **#7** Use `update_fields` on `update_scenario` and `update_metadata` save calls
- [x] **#18** Fix API/view status codes: not-found returns 404, "cannot edit default" returns 403, error pages have proper status
- [x] **#16** Removed `enabled` from YAML export — no longer presents non-editable field as editable
- [x] **#19** Added tests for `validate-yaml` and `import-yaml` API endpoints

### Low (consistency / UX polish)

- [ ] **#9** Extend site-wide base template instead of standalone base.html
- [x] **#10** Extract duplicated CSS into base.html shared block
- [x] **#11** Add confirmation dialog on toggle enabled/staff_only actions — `onclick="return confirm(...)"`
- [ ] **#12** Add server-side delete confirmation (dedicated confirm page or POST field)
- [ ] **#13** Add pagination or lazy loading to scenario list
- [x] **#14** Handle empty hidden field on form submit — added try/catch with `e.preventDefault()` and alert
- [x] **UX** Add Django messages framework — `messages.success()` on all mutation views, base.html renders messages
- [ ] **UX** Add breadcrumb navigation
- [x] **Arch** Extract shared test fixtures to `conftest.py`
- [x] **Arch** Removed DRF API layer (YAGNI) — deleted api_views.py, serializers.py, permissions.py; moved validate-yaml endpoint into views.py as plain Django view

### Architecture (added during fix work)

- [x] **Arch** Move `scenario_editor` from standalone app into `cms/scenario_editor/` submodule — removed from INSTALLED_APPS, updated all imports and URL config

---

## Fix Summary

Completed 2026-02-08. 109 tests passing (up from 104).

| Phase | Changes |
|-------|---------|
| Architecture | Moved `scenario_editor/` into `cms/scenario_editor/` submodule |
| Services | `CMSError` hierarchy, `_validate_user()`, slug validation, `transaction.atomic()`, `update_fields`, `PydanticValidationError` catch, `enabled` removed from export, structured logging |
| Views | Catch-all handlers, 403/404/500 status codes, slug validation, empty field validation, `messages.success()`, structured logging |
| API removal | Deleted `api_views.py`, `serializers.py`, `permissions.py` (YAGNI); moved validate-yaml endpoint into views.py as `JsonResponse` |
| Templates | XSS fixes (`json_script`, `escapeHtml`, DOM API), CSS dedup to base, confirm dialogs, messages display |
| Tests | Shared conftest.py, validate-yaml view tests, user validation, slug format, race condition, export content, view 404s, success messages, json_script context |

### Remaining items (not addressed — consistent with codebase patterns)

- **#9** Site-wide base template — every app (mission_control, risk_register, documentation) has its own base.html; no shared base exists in the project
- **#12** Server-side delete confirmation — JS `confirm()` is the established pattern across all apps (agents, risk register, etc.); server-side confirmation is only used for NGFW deprovisioning
- **#13** Pagination — no list view in the project uses pagination
- **UX** Breadcrumb navigation — no breadcrumb pattern exists in the project
