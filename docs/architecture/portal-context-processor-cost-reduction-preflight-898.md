# Portal Context-Processor Cost Reduction Preflight (#898)

Status: pre-implementation guidance

Date: 2026-06-16

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/898>

Companion docs:

- [`portal-context-processor-audit-852.md`](portal-context-processor-audit-852.md)
- [`portal-context-processor-preflight-852.md`](portal-context-processor-preflight-852.md)
- [`asgi-render-integration-preflight-924.md`](asgi-render-integration-preflight-924.md)

## Scope Boundary

#898 is the cost-reduction follow-up from the #852 analytical audit. The
shipping contract is limited to reducing per-authenticated-HTML-render context
processor work:

- collapse repeated `user.groups` lookups to one request-scoped lookup;
- avoid the double `is_ctf_participant_only` evaluation;
- remove the `agent` / `request` FK N+1 in `cms.services.get_active_range()`;
- stop constructing full terminal active-range payloads on non-terminal pages
  while preserving a cheap sidebar `has_active_range` signal.

This is not the #684 active-range god-module extraction, not a CTF workflow
rewrite, and not a new observability or caching framework.

## Architecture Decisions

- Use request-scoped reuse for group membership, not cross-request caching.
  Group, staff, superuser, active-event, and range lifecycle state are
  authorization-sensitive and can change during a session.
- Keep the context-depth seam from #852:
  `none` / `nav` / `ctf` / `terminal_full`. The seam is server-owned; it must
  not be selected by query string, header, JavaScript, or other client input.
- Keep full active-range projection page-scoped to the terminal render.
  Non-terminal Mission Control pages and shared sidebars need only navigation
  flags and `has_active_range`.
- Keep range ownership and shape in CMS services and shared schemas.
  Presentation code may choose the depth of context it asks for; CMS and Engine
  must not learn template names, sidebar behavior, or request paths.
- Do not treat `SimpleLazyObject` as evidence by itself. If a globally included
  sidebar or base template reads the lazy value on every page, the work is still
  global. Evidence must come from rendered-page query counts.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #898 |
| --- | --- | --- |
| Global context registration | `config/settings.py` `TEMPLATES[...]["context_processors"]` | Change registration only with rendered-page tests proving included templates still get required context. |
| Active range ownership/query | `cms.services.get_active_range()`, `RangeInstance.objects`, `_validate_caller_user()` patterns | Add eager FK loading here; do not move range authorization to templates, views, or JavaScript. |
| Range/terminal shape | `shared.schemas.RangeContext`, `InstanceContext`, `mission_control.utils.build_connection_urls()`, `_terminal_instances_payload()` | Reuse the existing DTOs and terminal payload shape; no parallel terminal DTO. |
| Runtime IP overlay | `cms.services._common._resolve_runtime_ips()` and `_instance_contexts_from_range_spec()` | Keep runtime IP lookup terminal-full only and best-effort; do not duplicate range-spec flattening. |
| CTF role/group policy | `shared.auth` constants and predicates, `ctf.bridges.UserRole`, `get_user_role()` | Build group reuse underneath these contracts or adapt them to consume the request-scoped result; no group-name literals or second role schema. |
| CMS authoring permission | `shared.auth.can_edit_cms_authoring()` and `shared.context_processors.user_permissions()` | Preserve the canonical Threat Research/staff policy. |
| Template JSON safety | Django `json_script` in `mission_control/terminal.html` | Keep terminal JSON out of inline JavaScript interpolation. |
| Render evidence | `tests/integration/mission_control/test_page_renders.py`, `Client`, `CaptureQueriesContext` | Update or extend numeric rendered-page budgets; do not add a one-off measurement script as the closing proof. |
| Import boundaries | `.importlinter` contracts | Mission Control must not import CTF directly; CTF must not import Mission Control or Engine; CMS must not import presentation layers. |
| Logging/errors | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()`, `shared.errors.classify_user_message()` | Log aggregate route/query/timing data only; context processors stay fail-soft and server-logged. |

## Cross-Cutting Layers

- Auth surface: HTML renders pass through Django middleware,
  `AuthenticationMiddleware`, `login_required`, CTF decorators, and `request.user`.
  Anonymous users must keep the fast empty-context behavior.
- Authorization surface: active-range data still comes from
  `cms.services.get_active_range(user)` or a CMS-owned equivalent with the same
  user ownership filter. CTF navigation still goes through `ctf.bridges` and
  `shared.auth`.
- Validation surface: `RangeContext` / `InstanceContext` remain the template-safe
  shape checks. User shape checks follow the CMS `_validate_caller_user()` style.
- Template/XSS surface: terminal payloads stay embedded with `json_script` and
  Django escaping. The implementation must not reintroduce inline JSON strings.
- Secret/logging surface: instance UUIDs, private IPs, websocket paths, role
  flags, and event IDs are authorized UI data, not data for broad logs. Logs and
  test diagnostics should use aggregate counts, route names, user IDs, and
  sanitized IDs only.
- Env/config surface: this issue should not add an environment toggle. If a
  later follow-up adds one, it must use the existing Django settings helpers and
  be non-secret.
- OS/runtime exposure: evidence should be local tests and docs. Do not add a
  public diagnostic endpoint, process argv secret exposure, env dumps, or SQL
  dumps with sensitive literals.
- Error-envelope surface: context processor failures keep returning safe empty
  context and logging server-side. Any new user-visible diagnostic response must
  use authored messages via `shared.errors`.
- Persistence surface: no migration, durable metric table, or audit/event model
  is needed for #898.

## Extensibility Seam

The future extension point is the server-owned context depth, not a new global
context abstraction:

- `none`: anonymous or no authenticated navigation state.
- `nav`: shared navigation flags and cheap `has_active_range`.
- `ctf`: CTF role plus active event for CTF navigation/views.
- `terminal_full`: full `RangeContext`, scenario name, runtime IP overlay,
  `connection_urls`, and `terminal_instances`.

Future pages should be able to opt into a deeper context tier without changing
CMS range projections, CTF role contracts, or terminal payload schemas.

## Gotchas And Anti-Patterns

- The current terminal projection mutates `RangeContext.instances` when applying
  the CTF-only Kali filter. Do not share that mutated object across independent
  consumers or requests; project/copy before filtering if reuse creates aliasing.
- `has_active_range` must be cheap enough for the sidebar. It should not force
  runtime IP overlay, scenario lookup, connection URL building, or terminal JSON
  construction on dashboard/help/settings pages.
- Do not centralize all context in a helper that imports every app; that breaks
  import-linter boundaries and muddles ownership.
- Do not duplicate group predicates, CTF role schemas, range DTOs, validation
  helpers, exception hierarchies, logging formatters, or query-budget frameworks.
- Do not weaken CSRF/session auth, CTF decorators, ADR guard, import-linter,
  template escaping, or rendered-page tests to make the query count lower.

## Non-Goals

- No full #684 module decomposition.
- No cross-request role/range cache or invalidation policy.
- No new Ground Control requirement; issue #898 is the authoritative contract.
- No new runtime metric emitter, public diagnostic endpoint, schema, migration,
  workflow change, or deployment/configuration knob.

## Validation

For this preflight documentation change:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups should also run, at minimum:

```bash
cd shifter/shifter_platform && uv run ruff check .
cd shifter/shifter_platform && uv run ruff format --check .
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
cd shifter/shifter_platform && uv run pytest tests/integration/mission_control/test_page_renders.py tests/mission_control/test_context_processors.py tests/shared/test_auth.py tests/ctf/test_auth.py
```
