# ACES Participant Runtime Mission Control Projection Preflight

Issue: GitHub #1290, "21 - ACES migration: project participant runtime access in
Mission Control."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, serializers, views, templates, JavaScript, websocket
behavior, Guacamole behavior, CTF flows, command dispatch, or conformance
claims. This is a requirement-free run; the GitHub issue is the shipping
contract.

## Boundary

The controlling decisions remain ADR-024, ADR-025, ADR-027, the parent #1236
participant-runtime/Mission Control preflight, the #1288 participant-runtime
sidecar/API slice, and the #1276 Mission Control range projection slice:

- Current Shifter range, terminal, Guacamole, NGFW, and CTF participant access
  workflows remain authoritative and compatible.
- The #1288 participant-runtime sidecar and read APIs already exist for
  `participant_implementation` and `participant_runtime` history/detail reads.
  #1290 is a presentation/API projection slice over those records and existing
  access surfaces; it is not a new storage or lifecycle slice.
- Access-channel availability is a read-only projection over Shifter services.
  It must not become an authorization, lifecycle, token, credential, evidence,
  redaction, or command-dispatch authority.
- `participant_access_channel` is not currently a supported
  `AcesParticipantRuntimeRecord` kind. If a future issue needs persisted ACES
  access-channel sidecars, it must add them through shared contracts,
  validators, model/migration, projection helpers, and tests. #1290 should not
  hide access-channel records inside existing participant-runtime payloads.

## Architecture Decisions

- Keep the existing Mission Control range contract stable. The legacy
  `mission_control.views._ranges.get_range` path and canonical
  `mission_control.api.ranges.CurrentRangeView` path already return the same
  optional `aces_projection` operation summary. Participant/runtime/access
  projections must preserve existing keys and non-ACES behavior; absent ACES
  rows remain `null`/empty and do not alter range status, action buttons,
  websocket reconnects, terminal visibility, or Guacamole availability.
- Use a shared presentation helper below both range read paths. Build on
  `shared.aces.presentation.build_range_aces_projection` and
  `shared.aces.participant_runtime_projections.list_participant_runtime_records`
  rather than querying sidecar models from Mission Control views, templates, or
  JavaScript. Detail/history reads stay on the existing #1288 endpoints.
- Keep the output namespaced and read-only. If existing range responses grow a
  participant/runtime summary, add an optional ACES-namespaced object or
  optional child fields while preserving the current `aces_projection` shape.
  Do not overload `range.status`, `connection_urls`, `error_message`,
  `terminal_url`, CTF `range_status`, or Guacamole bootstrap status with ACES
  participant/runtime meaning.
- Treat access channels as explicit discriminated projections. Expected kinds
  are browser terminal, Guacamole RDP, Guacamole range SSH, Guacamole NGFW SSH,
  and backend command dispatch. These records describe availability and target
  refs only; they do not contain signed URLs, bearer tokens, private keys,
  passwords, commands, prompt/script bodies, terminal streams, or provider
  diagnostics.
- Reuse existing access authorities. Browser terminal access remains
  `SSHConsumer` -> `terminal_executor` -> `engine.services.connect_terminal`
  with process/user caps and session audit. Guacamole access remains
  `GuacamoleBootstrapRequest.Protocol`, bootstrap workers, owner-scoped polling,
  TTL, consume-and-clear delivery, and engine credential resolution. NGFW SSH
  remains `engine.services.connect_ngfw_terminal`. Backend command dispatch
  remains the existing CMS/engine/provisioner dispatch path keyed by ids.
- Keep CTF participant flows event-scoped. Participant range pages and APIs use
  `ctf.views._access`, `ctf.services.range`, `ctf.bridges`, and CMS service
  facades. Do not make `CTFParticipant`, Django `User`, `RangeInstance`, or an
  ACES `participant_ref` interchangeable identities.
- Do not add a new ACES product surface. No `/api/v1/aces/` namespace,
  ACES-only dashboard, ACES-only websocket topic, duplicate event bus, duplicate
  error envelope, duplicate token scope hierarchy, or duplicate status enum is
  needed for this slice.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024, #1236 | Keep ACES parallel and parity-gated. |
| Operation range presenter | `shared.aces.presentation`, `shared.aces.projections`, #1276 | Compose with the existing optional `aces_projection`; do not duplicate operation projection logic. |
| Participant-runtime sidecar reads | `shared.aces.participant_runtime_projections`, #1288 endpoints | Use response-allowlisted projections, bounded limits, participant-ref filters, and profile/version constants. |
| Mission Control range reads | `mission_control.views._ranges.get_range`, `mission_control.api.ranges.CurrentRangeView` | Keep legacy and canonical range response shapes in lockstep. |
| Mission Control auth/scopes | `MissionControlReadAPIView`, `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `MISSION_CONTROL_RANGE_READ` | Authorize the Shifter range before sidecar reads. |
| API validation/errors | DRF serializers, `_validated`, `shared.api.errors`, `MissionControlAPIView` legacy helpers | Use serializers and existing envelopes; no app-local parsers or ACES errors. |
| Browser terminal | `mission_control.consumers.SSHConsumer`, `terminal_sessions`, `terminal_executor`, `engine.services.connect_terminal` | Preserve auth, caps, close codes, audit, and engine secret/ownership checks. |
| Guacamole | `mission_control.guacamole`, `guacamole_bootstrap`, `GuacamoleBootstrapRequest`, `_guacamole*` views | Preserve protocol choices, token lifecycle, bounded workers, owner-scoped status/open, and consume-and-clear. |
| NGFW SSH | `engine.services.connect_ngfw_terminal`, `mission_control.api.guacamole.GuacamoleNGFWSSHURLView` | Keep NGFW ownership/state/secret checks in engine services. |
| CTF participant range | `ctf.services.range`, `ctf.views._access`, `ctf.views.api.ranges`, `ctf.bridges` | Resolve participants through CTF services and event ownership, not sidecar row presence. |
| Range status propagation | `RangeEventOutbox`, `drain_range_event_outbox`, `cms.handlers.range_events`, `reconcile_range_events`, `RangeStatusConsumer` | Status remains Shifter lifecycle state; ACES display is secondary. |
| Logging/audit | `shared.log_sanitize`, `risk_register.services.audit_log`, Guacamole/terminal audit helpers | Log sanitized ids, counts, statuses, discriminators, and refs only. |
| Config/runtime env | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, render/deploy tests | New flags or limits, if unavoidable, must be explicit settings with runtime coverage. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep ACES contracts behind `shared` and app crossings behind service facades. |

## Cross-Cutting Layers The Design Must Pass

- Session/API-token authentication: canonical range/projection APIs pass through
  `ApiTokenAuthentication` and `SessionAuthentication` via
  `IsAuthenticatedSessionOrApiToken`. Malformed bearer tokens fail closed and
  must not fall through to a logged-in session.
- API-token scopes: current range and participant-runtime projection reads use
  exact `mission_control:range:read`. Guacamole bootstrap/open remains
  `mission_control:guacamole:read`. Add a new scope only for a genuinely new
  audience, and then update `KNOWN_SCOPES` and token tests.
- Product authorization: Mission Control resolves the actor and owned range
  through `cms.services.get_active_range` / `get_range_by_request_id` before
  any sidecar projection lookup. CTF resolves active participants and organizer
  ownership through CTF helpers. Unknown and not-owned ids should stay
  indistinguishable where current services do that.
- Request shape validation: route ids, query limits, participant-ref filters,
  projection-kind filters, and access-channel filters use DRF serializers or
  shared validators. Do not parse UUIDs, limits, or enum strings ad hoc in
  views or JavaScript.
- Sidecar validation: persisted participant-runtime rows already pass
  `shared.schemas.aces_participant_runtime` for profile/version, record kind,
  idempotency, aware timestamps, payload digest, bounded JSON, single-line refs,
  retention/redaction values, and secret-bearing key/value rejection.
- Response and presentation redaction: API response fields must come from
  `shared.aces.participant_runtime_projections` or a shared presentation helper
  with its own allowlist. Dashboard/terminal/CTF presentation must further
  reduce values to compact labels, timestamps, refs, counts, and channel
  discriminators.
- Secret-handling surface: responses, templates, JavaScript, logs, audit rows,
  events, DLQs, tests, docs examples, screenshots, argv, env literals, and
  workflow logs must exclude private keys, RDP passwords, Guacamole token URLs,
  bearer/presigned URLs, upload tokens, prompt bodies, script bodies, command
  strings, terminal streams, transcripts, CTF flags, cloud credentials,
  provider dumps, Terraform/SSM/SSH output, and raw ACES payloads.
- OS/process exposure: #1290 should be DB/API/UI projection work. It must not
  introduce subprocess commands, shell strings, Kubernetes Job env literals, or
  argv-carried payloads/tokens. Terminal and Guacamole continue through their
  existing structured service calls keyed by ids.
- Error envelopes: canonical `/api/v1` failures use `shared.api.errors`.
  Legacy Mission Control routes keep flat error compatibility. Terminal
  failures use `WebSocketCloseCode`; Guacamole bootstrap uses curated
  `BootstrapFailure`/status messages. Raw ACES, DB, SSH, Guacamole, provider,
  storage, or CTF exceptions stay in sanitized logs.
- Event/websocket layer: range status websocket hydrate/stream behavior remains
  `RangeStatusConsumer` over Shifter status. ACES participant/access projection
  display must not add a websocket topic or bypass outbox/reconciler recovery.
- Template/JavaScript layer: ACES-derived values are inserted with
  `textContent`, safe attributes, or `json_script`-style escaped data. Do not
  concatenate ACES strings into `innerHTML`, inline scripts, `data-*` dumps, or
  URL-bearing attributes.
- Config/env validators: this slice should not need new env. If a feature flag,
  limit, or polling interval becomes configurable, add it through Django
  settings plus `config/env-manifest.json`, runtime inventory/render tests, and
  deployment validation. Do not add handler-local `os.environ` reads.
- Import boundaries: Mission Control may use `shared` and approved CMS/engine
  service facades. CTF must not import Mission Control or engine internals for
  projections; use CTF services/bridges and shared helpers.

## Extensibility View

The extension point is a shared Mission Control presentation projection
parameterized by:

- `request_id` as the Shifter/ACES correlation key;
- participant-runtime record kinds (`participant_implementation`,
  `participant_runtime`) and `participant_ref` filters;
- contract profile/version and participant-runtime profile;
- access-channel kind (`browser_terminal`, `guacamole_rdp`,
  `guacamole_range_ssh`, `guacamole_ngfw_ssh`, `backend_command`);
- product surface allowlist, for example current range summary, terminal page,
  CTF participant range page, or future detail panel;
- latest-only versus bounded small history.

The next likely variation is another participant-runtime contract version,
another backend profile, or another access channel. That should add one
profile/kind branch behind shared validators and the presentation helper, not
copies across range views, CTF views, Guacamole views, terminal JavaScript,
websocket consumers, or dashboard status switches.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
- `docs/architecture/aces-participant-runtime-api-sidecars-preflight-1288.md`
- `docs/architecture/aces-mission-control-range-projections-preflight-1276.md`
- `docs/architecture/terminal-websocket-capacity-847.md`
- `docs/architecture/guacamole-token-lifecycle-preflight-939.md`
- `docs/architecture/aces-migration-parity-inventory.yaml` rows for
  participant-runtime sidecars, participant access projection, Mission Control
  range UI, terminal/Guacamole, and CTF range status
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/aces_participant_runtime.py`
- `shifter/shifter_platform/shared/api/**`
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/mission_control/api/**`
- `shifter/shifter_platform/mission_control/views/_ranges.py`
- `shifter/shifter_platform/mission_control/context_processors.py`
- `shifter/shifter_platform/mission_control/consumers.py`
- `shifter/shifter_platform/mission_control/status_consumers.py`
- `shifter/shifter_platform/mission_control/guacamole*.py`
- `shifter/shifter_platform/mission_control/models.py`
- `shifter/shifter_platform/templates/mission_control/**`
- `shifter/shifter_platform/static/js/dashboard.js`
- `shifter/shifter_platform/static/js/terminal*.js`
- `shifter/shifter_platform/engine/services/_terminal.py`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/handlers/**`
- `shifter/shifter_platform/ctf/views/**`
- `shifter/shifter_platform/ctf/services/range/**`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/config/**` and
  `shifter/installation/runtime_inventory.py` only if settings change
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, and `.gc/plan-rules.md`

## Regression Evidence Expectations

- Legacy/non-ACES Mission Control range API and dashboard tests prove response
  compatibility when no participant-runtime rows exist.
- Canonical and legacy range read tests prove any new optional projection field
  is present/absent consistently across both paths.
- Participant-runtime projection tests seed sidecar rows and prove only
  response-allowlisted fields are visible, with participant-ref filtering and
  bounded limits delegated to the shared read seam.
- Access-channel projection tests prove discriminators are explicit and
  reference-only, and that terminal/Guacamole/NGFW/backend command projection
  presence does not grant access or change lifecycle state.
- Terminal tests prove websocket close codes, session caps, audit behavior,
  connection URL shape, and `terminal-init.js` behavior are unchanged.
- Guacamole tests prove RDP/range SSH/NGFW SSH bootstrap responses, status/open
  polling, TTL, consume-and-clear, queue-full, and single-use delivery behavior
  are unchanged.
- CTF tests prove participant range status/access and organizer range actions
  remain event-scoped and compatible.
- Frontend tests prove ACES-derived labels/refs are inserted as text and do not
  enter transitional-state switch logic, `innerHTML`, or inline script blobs.
- Import/config checks cover `.importlinter`, layer imports, ADR guard, and
  env-manifest/runtime-inventory changes when boundaries or settings change.

## Gotchas And Anti-Patterns

- Do not conflate ACES participant implementation, ACES participant runtime,
  access channel, Django `User`, `CTFParticipant`, `RangeInstance`,
  `engine.Range`, terminal instance UUID, NGFW app UUID, or backend command
  target.
- Do not authorize by sidecar row presence, `participant_ref`, visible UI
  state, frontend channel kind, `range_id`, `range_instance_id`, or
  `connection_urls`.
- Do not add `participant_access_channel` as JSON inside existing
  `participant_runtime` payloads. Add a real shared contract/model/projection
  in a future storage issue if persisted access-channel sidecars are needed.
- Do not make access-channel projections contain signed Guacamole URLs,
  websocket tokens, credentials, private IP secrets, commands, prompt/script
  bodies, terminal output, or provider diagnostics.
- Do not change `DashboardManager._isTransitionalState()`, range status
  websocket payloads, `RangeEventOutbox`, CTF status sync, Guacamole bootstrap
  status, or terminal session caps to accommodate ACES display data.
- Do not add a global context-processor ACES query; the nav versus terminal
  payload cost boundary from #898 remains.
- Do not duplicate schemas, serializers, exception hierarchies, scopes, event
  buses, websocket topics, audit tables, terminal session stores, Guacamole
  token stores, or status enums.
- Do not weaken ADR guard, import-linter, API-token fail-closed behavior,
  secret scanning, redaction rules, terminal capacity controls, Guacamole token
  lifecycle controls, or CTF event-scoped access.

## Non-Goals

- No implementation in this preflight note.
- No mutation APIs, participant-runtime lifecycle controls, command execution,
  evidence capture, new sidecar record kind, cleanup job, websocket channel,
  Guacamole redesign, terminal redesign, CTF workflow change, or backend
  manifest participant-runtime claim.
- No replacement of current Mission Control range APIs/UI, terminal websocket
  behavior, Guacamole bootstrap/token lifecycle, NGFW SSH flow, range status
  websockets, CTF participant range views, CTF scoring/access semantics, or
  backend command dispatch.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation touching `shifter/shifter_platform` should also
run the targeted Mission Control API/UI/frontend tests, participant-runtime
sidecar/projection tests, terminal websocket tests, Guacamole bootstrap tests,
CTF participant range tests, import-linter checks, and any config/deployment
checks required by touched files.
