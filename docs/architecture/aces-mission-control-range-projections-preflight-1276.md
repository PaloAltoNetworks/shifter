# ACES Mission Control Range Projection Preflight

Issue: GitHub #1276, "17 - ACES migration: surface ACES-backed range
projections in Mission Control UI."

Status: pre-implementation architecture guidance. This note does not implement
UI, API, serializers, services, models, migrations, websocket changes, or test
changes. This is a requirement-free run; the GitHub issue is the shipping
contract.

## Boundary

The controlling decisions remain ADR-024, ADR-025, ADR-027, the parent #1234
operation projection design, and the #1275 read-only API projection design:

- `engine.Range.status`, `shared.enums.ResourceStatus`, and
  `cms.RangeInstance.status` remain Shifter's lifecycle authority and
  compatibility projection.
- Mission Control range status cards and `dashboard.js` continue to render the
  Shifter range lifecycle. ACES-backed operation state may be shown only as a
  read-only, secondary projection.
- The existing range-status websocket remains Shifter lifecycle fanout:
  hydrate current `RangeInstance` status on connect, then stream
  `range.status.updated` deltas. Do not add ACES-only websocket topics or make
  ACES observations control reconnect, timeout, action-button, or terminal
  availability behavior.
- `request_id` is the ACES/Shifter correlation key. `range_id` remains a
  Shifter projection/backfill key and is not sufficient for ACES lookup.
- Mission Control is the product UI boundary for this slice. Do not build an
  ACES-only range page, ACES-only dashboard, or parallel status taxonomy.
- Runtime snapshots are operational observations. They are not template data
  stores, JavaScript state dumps, provider dumps, audit logs, prompts, command
  transcripts, CTF evidence, or experiment archives.

## Architecture Decisions

- Reuse the #1275 read seam. Mission Control presentation code must read ACES
  records through `shared.aces.projections.list_operation_records` or through
  the existing `/api/v1/mission-control/range/<request_id>/aces/...` endpoints.
  It must not import `shared.models.AcesOperationRecord` or inspect raw
  sidecar payloads from views, templates, or JavaScript.
- Keep ACES data namespaced in output. If the current range response grows
  presentation data, add an optional object such as `aces_projection`; do not
  overload `range.status`, `status`, `error_message`, or `connection_urls` with
  ACES meaning.
- Preserve both current range read paths when they are both still used:
  `mission_control.views._ranges.get_range` backs the existing dashboard route,
  while `mission_control.api.ranges.CurrentRangeView` backs the canonical
  `/api/v1` route. Any shared ACES presentation helper must sit below both or
  one path must deliberately call the existing #1275 endpoint. Do not let the
  legacy and canonical Mission Control range shapes drift silently.
- Authorize before projection lookup. A page or API path must first resolve the
  actor and owned range through `cms.services.get_active_range` or
  `cms.services.get_range_by_request_id`; sidecar row existence is never an
  authorization signal.
- Render only a compact summary. The dashboard/status-card surface should show
  latest operation/status/snapshot facts, bounded timestamps, digests, and
  reference ids. It should not render record history by default or full nested
  snapshot resources unless a product-specific allowlist summarizes them.
- Treat snapshot `resources` as still presentation-sensitive. Even though
  sidecar validators and `shared.aces.projections` have bounded them for API
  return, the UI should reduce them to counts, lifecycle labels, and stable
  references rather than dumping raw nested structures into templates or DOM.
- Keep missing ACES rows boring. Legacy and non-ACES ranges must continue to
  render exactly as current ranges; the ACES projection is absent/null/empty and
  does not produce a warning state, failed state, extra websocket connection, or
  changed lifecycle affordance.
- Insert ACES-derived text with DOM-safe APIs. `dashboard.js` may continue to
  copy trusted template fragments with `innerHTML`, but any ACES/API-derived
  values must be assigned with `textContent`, attributes from allowlisted URLs
  only, or server-side escaping/json-safe helpers. Do not concatenate ACES
  strings into HTML.
- Keep page context cheap. Do not put ACES projection work in the global
  Mission Control context processor. It intentionally has a nav-tier versus
  terminal-tier cost boundary; ACES range projection belongs in the explicit
  dashboard/range API flow.
- Do not change lifecycle commands. Launch, cancel, destroy, pause, resume,
  terminal, Guacamole, and CTF participant range behavior continue to use
  existing CMS/engine service seams and Shifter statuses.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Parent ACES range projection design | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Keep ACES evidence separate from Shifter runtime authority. |
| Sidecar/API projection | `docs/architecture/aces-operation-api-projections-preflight-1275.md`, `shared.aces.projections`, `mission_control.api.aces` | Use redacted read helpers and existing endpoints; no raw sidecar serialization. |
| Status mapping | `shared.aces.status`, `engine.services.project_aces_operation_status`, `docs/architecture/aces-operation-status-range-event-preflight-1274.md` | ACES-to-Shifter lifecycle mapping stays at the adapter boundary, not in UI code. |
| Range authority | `cms.services.get_active_range`, `cms.services.get_range_by_request_id`, `cms.models.RangeInstance` | Resolve owned Shifter range state through the CMS service facade. |
| Mission Control range APIs | `mission_control.views._ranges.get_range`, `mission_control.api.ranges.CurrentRangeView` | Add optional presentation data without replacing the current range payload. |
| Dashboard presentation | `templates/mission_control/dashboard.html`, `static/js/dashboard.js`, `static/css/mc-dashboard.css` | Extend existing tiles/status cards; do not create an ACES-only UI. |
| Websocket lifecycle | `mission_control.handlers.process_range_event`, `mission_control.status_consumers.RangeStatusConsumer`, `shared.channels.payloads.RangeStatusChannelEvent` | Preserve Shifter status hydrate/stream behavior and channel payload shape unless a shared typed-contract change is intentionally made. |
| API auth and scopes | `MissionControlReadAPIView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `shared.api_tokens.scopes.MISSION_CONTROL_RANGE_READ` | Keep exact read gates for canonical API reads. |
| Legacy page auth | `@login_required`, `shared.auth.block_ctf_participant_only`, CMS ownership checks | Existing page/session flows remain session-authenticated and service-authorized. |
| Validation and errors | DRF serializers, `shared.api.errors`, `shared.errors.classify_user_message`, `MissionControlAPIView` legacy helpers | Keep canonical `/api/v1` envelopes and legacy flat payload compatibility where applicable. |
| Secret handling and logging | `shared.schemas.aces_operation`, `shared.log_sanitize.safe_log_value`, provisioner `log_redact` | Logs, responses, templates, and tests carry sanitized ids/statuses/refs only. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Mission Control reaches CMS through `cms.services`; ACES contracts stay behind `shared`. |

## Cross-Cutting Layers The Design Must Pass

- Session/API-token authentication: canonical ACES reads go through
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, and
  `MISSION_CONTROL_RANGE_READ`. Malformed bearer tokens fail closed per the
  existing API-token layer. Legacy dashboard reads remain `@login_required`.
- Product authorization: Mission Control actor resolution and
  `cms.services.get_active_range` / `get_range_by_request_id` prove ownership
  before any sidecar query. Unknown and not-owned request ids should remain
  indistinguishable to clients.
- Request shape validation: route `request_id` values use UUID path
  converters/DRF UUID fields; history limits use `AcesRecordQuerySerializer`
  and `MAX_HISTORY_LIMIT`. Do not parse UUIDs, limits, or record kinds in
  JavaScript by trusting arbitrary strings from the page.
- Sidecar contract validation: persisted ACES records already pass
  `shared.schemas.aces_operation` for record kind, contract profile/version,
  payload size, digests, diagnostic key allowlists, single-line refs, and
  high-confidence secret rejection.
- Response/presentation allowlists: `shared.aces.projections` applies the
  record-kind response allowlist. The UI must apply a second presentation
  allowlist, especially for runtime snapshot resources, because "safe to return
  from an API" is broader than "safe and useful in a dashboard card."
- Secret-handling surface: no secrets, CTF flags, prompts, command strings,
  generated scripts, transcripts, terminal output, Terraform/SSM/SSH output,
  provider dumps, package bodies, presigned URLs, bearer URLs, or raw snapshots
  may reach templates, JavaScript, logs, audit rows, screenshots, or tests.
- Event/websocket layer: correctness-critical status propagation remains
  `RangeEventOutbox` -> worker -> CMS handler/reconciler -> Mission Control
  advisory fanout. ACES projection display must not become a recovery path and
  must not bypass `RangeStatusConsumer` ownership checks.
- Error-envelope layer: canonical `/api/v1` failures use `shared.api.errors`.
  Legacy Mission Control endpoints keep their existing flat error payloads.
  Projection unavailability should degrade the ACES display only; it must not
  turn the Shifter range into failed/unknown.
- Template/JavaScript layer: Django template values remain escaped or generated
  as trusted route/config constants. ACES-derived values are DOM text, not
  HTML. Avoid storing raw ACES JSON in inline `<script>` blocks; if server-side
  JSON is unavoidable, use existing safe JSON patterns and a presentation
  schema, not sidecar payload passthrough.
- Observability layer: log request ids, statuses, counts, timings, contract
  profile/version, and diagnostic reference fingerprints. Do not log raw ACES
  payloads, snapshots, resource dictionaries, exception bodies, or response
  dumps.
- Config/env/OS exposure: #1276 should not need new env vars, subprocesses,
  shell commands, URL signing, Kubernetes Jobs, or workflow steps. Any future
  exposure flag, page-size default, or polling interval belongs in Django
  settings plus `config/env-manifest.json`, runtime inventory/rendering, and
  tests, not local `os.environ` reads or process argv.
- Whole-repo enforcement: changes under `shifter/shifter_platform` must satisfy
  Ruff, import-linter, ADR guard, API URL/schema tests, and the relevant
  Mission Control/API/frontend tests required by `.gc/plan-rules.md` and
  `AGENTS.md`.

## Extensibility Seam

The seam belongs in a shared presentation-projection helper or in a thin
Mission Control service wrapper over `shared.aces.projections`, not in
dashboard-specific JavaScript. It should be parameterized by:

- `request_id` as the correlation key;
- record kinds to summarize, initially latest operation status plus optional
  latest receipt/snapshot references;
- `contract_profile` and `contract_version`;
- latest-only versus small bounded history;
- product surface allowlist, for example dashboard summary versus future
  detail panel;
- a display label map that is explicitly distinct from `ResourceStatus`.

The next likely variation is a new backend profile, new operation-status
contract version, or a richer detail surface. That should add a projection
branch and tests behind this seam, not edits to `RangeContext.status`,
websocket payloads, CTF status sync, provider task state handling, or dashboard
status switch statements for every ACES vocabulary change.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-migration-adr.md`
- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
- `docs/architecture/aces-operation-status-range-event-preflight-1274.md`
- `docs/architecture/aces-operation-api-projections-preflight-1275.md`
- `docs/adr/index.yaml` entries for ADR-024, ADR-025, ADR-027, and the Mission
  Control flag-literal guardrail
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/aces_operation.py`
- `shifter/shifter_platform/shared/api/**`
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/models/range.py`
- `shifter/shifter_platform/mission_control/api/**`
- `shifter/shifter_platform/mission_control/views/_ranges.py`
- `shifter/shifter_platform/mission_control/context_processors.py`
- `shifter/shifter_platform/mission_control/handlers.py`
- `shifter/shifter_platform/mission_control/status_consumers.py`
- `shifter/shifter_platform/templates/mission_control/dashboard.html`
- `shifter/shifter_platform/static/js/dashboard.js`
- `shifter/shifter_platform/static/css/mc-dashboard.css`
- `shifter/shifter_platform/config/api_urls.py`
- `shifter/shifter_platform/config/settings.py` and
  `config/env-manifest.json` only if new settings are introduced
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, and `.gc/plan-rules.md`

## Regression Evidence Expectations

- Legacy non-ACES range dashboard/API tests prove current range launch,
  current-range display, pause/resume/cancel/destroy controls, status polling,
  and websocket updates remain unchanged when no ACES rows exist.
- ACES-backed range tests seed redacted sidecar records and prove the
  Mission Control presentation shows only the secondary ACES projection while
  `range.status` and lifecycle controls still come from Shifter state.
- Redaction tests prove templates and JavaScript do not receive raw `payload`,
  raw snapshots, provider dumps, command/prompt/script fields, flags,
  token-bearing refs, presigned URLs, or unbounded diagnostic text.
- Ownership tests cover unknown request ids, request ids owned by another user,
  session users, and API tokens with and without `MISSION_CONTROL_RANGE_READ`
  when canonical endpoints are used.
- Frontend tests cover safe DOM insertion (`textContent` or equivalent),
  absent/null projection handling, and no changes to transitional-state
  websocket reconnect/polling behavior.
- Contract tests cover legacy and canonical Mission Control range responses if
  both expose the projection.

## Gotchas And Anti-Patterns

- Do not conflate ACES operation status with Shifter `ResourceStatus`, CTF
  participant range status, experiment run status, provider task state, or UI
  display labels.
- Do not add ACES states to `DashboardManager._isTransitionalState()` or the
  main `currentRange.status` switch. Those branches are Shifter lifecycle only.
- Do not use `error_message` for raw ACES/provider failure text. Use bounded,
  user-safe status reasons or diagnostic references.
- Do not add a global context-processor query for ACES data; that would undo
  the existing nav-tier cost reduction and leak this concern onto every
  authenticated page.
- Do not expose `AcesOperationRecord.payload`, snapshot resources, or
  diagnostic refs through `innerHTML`, `data-*` blobs, inline scripts, logs, or
  screenshots.
- Do not authorize by sidecar row presence, scenario id, visible page state, or
  `range_id`. Authorize through actor/session/token gates and CMS ownership.
- Do not add an `/aces` product UI, ACES-only API namespace, ACES-only
  websocket topic, duplicate serializer hierarchy, duplicate status enum, or
  duplicate validation layer for this UI projection.
- Do not resurrect removed experiment UI paths or route ACES experiment-core
  semantics into range cards.
- Do not weaken ADR guard, import-linter, Mission Control flag-literal scans,
  API-token fail-closed behavior, or secret scanning to get the projection onto
  the page quickly.

## Non-Goals

- No implementation in this preflight note.
- No replacement of `engine.Range`, `cms.RangeInstance`, `ResourceStatus`,
  `RangeEventOutbox`, Mission Control range UX, CTF workflows, or terminal /
  Guacamole availability rules.
- No new ACES mutation endpoint, lifecycle command, websocket channel,
  reconciler, cleanup job, provider call, or runtime config knob.
- No raw ACES package/source exposure, execution-plan body, prompt, generated
  script, command string, transcript, provider dump, token-bearing URL, CTF
  flag, or experiment evidence archive.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation under `shifter/shifter_platform` should also run
the Mission Control dashboard/API tests, ACES API/projection tests, websocket
consumer tests, shared API-token/error tests, frontend tests for
`dashboard.js`, Ruff, import-linter, and any changed subsystem checks required
by `.gc/plan-rules.md` and `AGENTS.md`.
