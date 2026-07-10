# ACES Participant Runtime API And Sidecar Preflight

Issue: GitHub #1288, "19 - ACES migration: implement participant runtime API
and storage sidecars."

Status: pre-implementation architecture guidance. This note does not implement
models, migrations, APIs, serializers, services, workers, UI, or conformance
checks, and it is not an implementation plan. This is a requirement-free run;
the GitHub issue is the shipping contract.

## Boundary

The controlling decisions remain ADR-024, ADR-027, and the parent #1236
participant-runtime/Mission Control preflight:

- Current Shifter participant, runtime, range, CTF, and Mission Control
  behavior remains authoritative until a later ACES path passes parity and
  conformance gates.
- #1288 is the first participant-runtime storage and read-projection slice. It
  may persist version/profile-keyed ACES participant implementation/runtime
  sidecar records and expose read-only projection fields, but it must not move
  lifecycle, access, scoring, challenge, experiment, terminal, Guacamole, or
  range authority out of the existing product tables and services.
- The existing `shared.models.AcesOperationRecord` pattern is the incumbent for
  sidecar persistence shape and read projection discipline. It should guide
  #1288, but participant-runtime records must not be stuffed into operation
  sidecars unless they are truly operation receipt/status/snapshot records.
- ADR-027 removed the legacy `cms.experiments` app. Any experiment participant
  runtime semantics must come from the new ACES-backed design, not from
  reintroducing `ExperimentRun` metadata or old experiment status strings.

## Architecture Decisions

- Use first-class participant-runtime sidecar persistence. Do not store
  canonical ACES participant implementation, runtime, access-channel, history,
  or evidence records in `RangeInstance.range_spec`,
  `Range.provisioned_instances`, `Range.range_config`,
  deleted `ExperimentRun.metadata`, event payloads, `AuditLog` JSON, templates,
  or frontend state.
- Put discriminators in columns or typed shared DTO fields, not only in JSON:
  contract kind, contract version, contract profile, participant-runtime
  profile, capability/projection kind, owner, source timestamp, idempotency key,
  payload digest, retention timestamp/class, and redaction state/policy.
- Keep sidecar correlation scalar and cross-layer safe. Store Shifter ids and
  refs such as `request_id`, optional `range_id`, optional `range_instance_id`,
  optional CTF participant/event refs, user refs, operation ids, and access
  channel ids as bounded references. Do not add cross-app foreign keys from the
  shared ACES boundary to CMS, engine, CTF, or Mission Control models.
- Validate at the shared boundary before persistence. Follow the
  `shared.schemas.aces_operation` / `shared.schemas.aces_package_source`
  pattern: pure validators, allowlisted fields, bounded JSON, digest checks,
  single-line refs, supported profile/version checks, and secret/raw-content
  rejection before `save()`.
- Apply response redaction separately from persistence validation. A persisted
  sidecar payload is not automatically public API material. Read APIs should
  consume serializer-ready projections from a shared `shared.aces.*` read seam
  that allowlists fields per projection kind.
- Keep product authorization before sidecar lookup. A Mission Control caller
  must prove range/request ownership through `cms.services.get_range_by_request_id`
  or the existing range read service before any participant sidecar query. CTF
  projections must resolve participants through event-scoped CTF services and
  bridges. Not-owned and unknown ids should collapse to the existing not-found
  behavior.
- Preserve current runtime access channels. Browser terminal, Guacamole RDP/SSH,
  NGFW SSH, CTF participant range pages, and backend command dispatch may be
  referenced as read-only access-channel projections, but their authorization,
  capacity, token lifecycle, secret retrieval, auditing, and runtime behavior
  stay in Mission Control and engine services.
- Do not update the backend manifest to claim ACES `participant_runtime`.
  Shifter still publishes the `provisioning-only` capability until ACES
  participant-runtime lifecycle/history/evidence contracts exist and Shifter
  passes conformance without weakening current gates.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Migration doctrine | `docs/architecture/aces-migration-adr.md`, ADR-024, `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md` | Keep ACES parallel, sidecar-backed, and parity-gated. |
| Operation sidecar pattern | `shared.models.AcesOperationRecord`, `shared.aces.operations`, `shared.aces.projections`, `shared.schemas.aces_operation` | Mirror its validation, idempotency, retention, digest, and projection approach where applicable; do not overload operation semantics. |
| ACES profile source | `shared.aces.contracts`, `shared.aces.manifest` | Use Shifter-supported profile/version constants rather than app-local strings. |
| Package-source provenance style | `cms.models.AcesPackageSource`, `shared.schemas.aces_package_source`, `cms.scenarios.registry` | Reuse reference-only, allowlist-first provenance rules. |
| Mission Control API base | `MissionControlReadAPIView`, `_validated`, `AcesRecordQuerySerializer`, `mission_control.api.urls` | Use existing read gates, serializers, bounded query limits, and versioned route namespace. |
| Mission Control auth | `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `mission_control_actor_user`, `shared.api_tokens.scopes.MISSION_CONTROL_RANGE_READ` | Reuse session/API-token gates and exact read scope for range-owned projections. |
| CTF actor boundary | `ctf.services.participant`, `ctf.views._access`, `ctf.api._base`, `ctf.bridges` | Resolve participant identity through event-scoped helpers and CTF bridges; no direct Mission Control/engine imports. |
| CMS range ownership | `cms.services.get_range_by_request_id`, `get_active_range`, `RangeContext`, `RangeInstance` | Authorize by product service seams and keep `range_spec` as Shifter hydrated-spec storage only. |
| Engine runtime authority | `engine.models.Range`, `engine.services`, `RangeEventOutbox`, `engine.services.project_aces_operation_status` | Runtime state and status convergence stay engine/outbox/reconciler owned. |
| Terminal access | `mission_control.consumers.SSHConsumer`, `terminal_sessions`, `terminal_executor`, `engine.services.connect_terminal` | Keep session caps, executor bounds, audit, ownership checks, and secret fetches in existing services. |
| Guacamole access | `mission_control.guacamole`, `guacamole_bootstrap`, `GuacamoleBootstrapRequest` | Keep token signing, worker bounds, TTL, owner-scoped polling, and consume-and-clear lifecycle. |
| Errors | `shared.api.errors`, `shared.errors`, `shared.exceptions.CMSError`, `ctf.exceptions` | Translate through existing envelopes and domain exceptions; no ACES-only exception hierarchy. |
| Logging/audit | `shared.log_sanitize`, `risk_register.services.audit_log`, CTF audit helpers | Log/audit ids, statuses, redaction classes, and refs only. |
| Config/runtime env | `config/settings.py`, `config/env-manifest.json`, `shifter/installation/runtime_inventory.py`, `scripts/gcp/render_runtime_env.py` | New knobs need canonical settings and inventory/render coverage; no handler-local env reads. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | Keep ACES contracts behind `shared` and app-to-app access behind service facades. |

## Cross-Cutting Layers The Design Must Pass

- Session/API-token authentication: `/api/v1` requests pass through
  `ApiTokenAuthentication` and `SessionAuthentication`. Invalid bearer tokens
  fail closed and must not fall through to session behavior.
- API-token scopes: Mission Control range-owned participant/runtime reads use
  `mission_control:range:read`. CTF participant-facing reads, if added, use the
  existing `ctf:play:read`; organizer/event reads use `ctf:event:read`; CMS
  authoring reads use `cms:authoring:read`. Add a new exact scope only if this
  proves to be a new audience, and update `KNOWN_SCOPES` and tests.
- Product authorization: Mission Control must authorize range/request ownership
  before sidecar reads. CTF must use `eligible_participant_q`,
  `get_participant_by_user(..., event_id=...)`, organizer ownership checks, and
  `ctf.bridges` for CMS access. Sidecar existence is never authorization.
- Request shape validation: route ids, query limits, projection kinds, profile
  filters, and access-channel filters use DRF serializers or shared validators.
  Do not parse UUIDs, enum-like strings, or limits ad hoc in views.
- Sidecar contract validation: shared validators enforce supported
  contract/profile/version pairs, profile/capability discriminators, idempotency
  key shape, timestamp awareness, digest equality, owner values, retention and
  redaction fields, field allowlists, size caps, single-line refs, and
  secret-bearing key/value rejection.
- Secret-handling surface: sidecar payloads, API responses, logs, audit rows,
  events, DLQs, test fixtures, docs examples, OpenAPI examples, argv, env
  literals, and workflow logs must exclude private keys, RDP passwords,
  Guacamole token URLs, bearer or presigned URLs, upload tokens, prompt bodies,
  scripts, command strings, terminal streams, transcripts, CTF flags, cloud
  credentials, provider dumps, Terraform/SSM/SSH output, and raw ACES package
  bodies.
- OS/process exposure: #1288 should be DB/API projection work. It should not
  introduce subprocess commands, shell strings, Kubernetes Job env literals, or
  argv-carried ACES payloads. Runtime access continues through structured
  service calls keyed by ids.
- Error envelopes: canonical `/api/v1` responses use `shared.api.errors`.
  Legacy Mission Control behavior, if touched, keeps `MissionControlAPIView`
  flat-error compatibility. Raw ACES parser, provider, DB, SSH, Guacamole,
  storage, or CTF exceptions are logged safely and returned as curated messages.
- Event/projection surface: correctness-critical range status still passes
  through `RangeEventOutbox`, drainers, CMS handlers, CTF bridge signals, and
  `reconcile_range_events`. Participant-runtime sidecar writes must not add a
  second event bus, websocket topic, or status pipeline.
- Logging/observability: use `safe_log_value`, `safe_log_id`, or
  `safe_log_fingerprint` as appropriate. Include counts, durations, profile
  names, status names, opaque ids, redaction states, and reference ids; never
  payload dumps.
- Config/env validators: retention periods, projection limits, pruning cadence,
  profile enablement, or access-channel exposure flags need Django settings,
  env-manifest/runtime-inventory coverage, render tests where applicable, and
  no new local secret files.
- Import boundaries: app layers may import `shared` and approved service
  facades only. Mission Control must not import CTF directly; CTF must not
  import engine or Mission Control directly; only `shared` may own ACES/CyberScript
  contract shims.

## Extensibility Seam

The seam belongs in a shared participant-runtime record/projection boundary,
parameterized by:

- contract kind/version/profile;
- participant-runtime profile;
- capability or projection kind;
- access-channel kind (`terminal`, `guacamole_rdp`, `guacamole_ssh`,
  `ngfw_ssh`, `backend_command`, or later values);
- Shifter correlation refs (`request_id`, range/range-instance refs, CTF
  participant/event refs, user refs);
- retention class/expiry and redaction state/policy;
- bounded response projection policy.

The next reasonable variation is an ACES participant-runtime contract version,
another backend profile, another access channel, or a different product
consumer. That should add one profile/projection branch behind shared validators
and projection helpers, not copies across Mission Control views, CTF services,
CMS range queries, engine models, templates, or frontend schema files.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-participant-runtime-mission-control-preflight-1236.md`
- `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
- `docs/architecture/aces-operation-status-range-event-preflight-1274.md`
- `docs/architecture/aces-operation-api-projections-preflight-1275.md`
- `docs/architecture/aces-migration-parity-inventory.yaml` rows
  `aces.participant-runtime-sidecars`, `aces.participant-access-projection`,
  `status.ctf-range`, `mission-control.terminal-guacamole`,
  `validation.participant-runtime-conformance`
- `docs/adr/index.yaml` entries for ADR-024, ADR-025, and ADR-027
- `shifter/shifter_platform/shared/models.py`
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/**`
- `shifter/shifter_platform/shared/api/**`
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/mission_control/api/**`
- `shifter/shifter_platform/mission_control/consumers.py`
- `shifter/shifter_platform/mission_control/guacamole*.py`
- `shifter/shifter_platform/engine/models.py`
- `shifter/shifter_platform/engine/services/**`
- `shifter/shifter_platform/cms/models/range.py`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/handlers/**`
- `shifter/shifter_platform/ctf/services/participant/**`
- `shifter/shifter_platform/ctf/services/range/**`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/risk_register/services.py`
- `shifter/shifter_platform/config/**` and `shifter/installation/runtime_inventory.py`
  if new settings are introduced
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, and `.gc/plan-rules.md`

## Regression Evidence Expectations

- Sidecar model/schema tests cover required ownership, idempotency, retention,
  redaction, profile/version, digest, timestamp, and field allowlist behavior.
- Idempotency tests prove identical replays converge and same-key content drift
  fails closed without partial writes.
- Redaction tests prove persistence rejects raw secrets/content and API
  projections additionally exclude non-public payload keys.
- Mission Control API tests cover session users, API tokens with
  `MISSION_CONTROL_RANGE_READ`, missing scopes, inactive token owners,
  malformed bearer tokens, unknown request ids, and not-owned request ids.
- CTF tests, when CTF projections are touched, cover event-scoped participant
  resolution, disqualified participant denial, organizer ownership, and bridge
  usage rather than direct CMS/engine imports.
- Compatibility tests prove existing Mission Control range, Guacamole,
  terminal, CTF participant range, and non-ACES range workflows behave the same
  when no participant-runtime sidecar rows exist.
- Import/config tests cover import-linter, layer-imports, ADR guard, and
  env-manifest/runtime-inventory changes when settings or boundaries change.

## Gotchas And Anti-Patterns

- Do not conflate `CTFParticipant`, Django `User`, `RangeInstance`,
  `engine.Range`, ACES participant implementation records, ACES runtime records,
  access channels, and backend execution targets.
- Do not overload `AcesOperationRecord` with non-operation participant data just
  to avoid a sidecar migration.
- Do not create duplicate ACES schemas, status enums, exception hierarchies,
  token scopes, API envelopes, event buses, websocket topics, terminal session
  stores, Guacamole token stores, audit tables, or artifact stores.
- Do not authorize by finding a sidecar row, UI element, scenario catalog row,
  or frontend field. Authorize through product service gates first.
- Do not make `range_id`, `range_instance_id`, CTF participant id, or user id
  alone the participant-runtime identity. They are Shifter correlation refs and
  need the explicit participant-runtime profile/capability discriminator.
- Do not copy raw commands, prompts, scripts, transcripts, terminal output,
  CTF flags, private keys, RDP passwords, Guacamole token URLs, presigned URLs,
  provider dumps, or cloud credentials into sidecars, API responses, logs,
  audit rows, events, docs, or tests.
- Do not add `/api/v1/aces/`, wildcard scopes, broad `aces:*` audiences, or
  handler-local `os.environ` reads for this slice.
- Do not weaken ADR guard, import-linter, API-token exact-scope validation,
  DRF error handling, terminal session caps, Guacamole token lifecycle controls,
  secret scanning, or runtime env inventory to make the ACES path easier.

## Non-Goals

- No runtime implementation in this preflight note.
- No mutation APIs, lifecycle controls, command dispatch, evidence capture,
  experiment execution, websocket changes, Guacamole changes, terminal changes,
  cleanup jobs, UI changes, or conformance publication.
- No replacement of `engine.Range`, `cms.RangeInstance`, CTF participant range
  workflows, Mission Control range UX, Guacamole/bootstrap, terminal access,
  `RangeEventOutbox`, or `AuditLog`.
- No ACES `participant_runtime` backend capability claim.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation touching `shifter/shifter_platform` should also
run the relevant shared ACES sidecar/projection tests, Mission Control API
tests, CTF participant/range tests, engine/CMS range event tests, import-linter
checks, and any stack-native checks required by `AGENTS.md` and
`.gc/plan-rules.md`.
