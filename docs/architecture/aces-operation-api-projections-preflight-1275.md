# ACES Operation API Projections Preflight

Issue: GitHub #1275, "16 - ACES migration: expose read-only operation
status and snapshot APIs."

Status: pre-implementation architecture guidance. This note does not implement
API routes, serializers, services, models, migrations, UI, or cleanup jobs, and
it is not an implementation plan. This is a requirement-free run; the GitHub
issue is the shipping contract.

## Boundary

The controlling decisions remain ADR-024 and the parent #1234 operation
persistence/projection design:

- `shared.models.AcesOperationRecord` is the canonical ACES sidecar for
  operation receipts, operation statuses, runtime snapshots, and execution-plan
  references.
- `engine.Range` and `cms.RangeInstance` remain Shifter's runtime authority and
  compatibility projection. Read APIs may summarize sidecar state, but they do
  not move lifecycle authority out of the existing range services, event
  outbox, CMS projection handlers, or reconciler.
- `request_id` is the Shifter operation correlation key. `range_id` remains a
  projection/backfill key only and can be absent in request-first flows.
- This issue exposes read-only projections for Mission Control and CMS
  consumers. It must not create an ACES-only management API, mutation API,
  event bus, websocket channel, audit store, status enum, or exception envelope.
- Runtime snapshots are operational observations. They are not experiment
  archives, audit logs, provider dumps, raw package stores, prompt/script
  stores, or CTF evidence stores.

## Architecture Decisions

- Put read surfaces behind the existing product API namespaces. Mission Control
  range-owned reads belong under the current `/api/v1/mission-control/`
  boundary and CMS authoring/inspection reads belong under the current
  `/api/v1/cms/` boundary. Do not add a parallel `/api/v1/aces/` product
  surface for this slice.
- Reuse the existing authenticated read gates. Mission Control read APIs use
  `MissionControlReadAPIView` or equivalent `IsAuthenticatedSessionOrApiToken`,
  `HasMissionControlActor`, and `MISSION_CONTROL_RANGE_READ` composition. CMS
  reads use `CMS_READ_PERMISSIONS`.
- Perform service-layer authorization before sidecar lookup. Mission Control
  callers must first prove access to the range/request through `cms.services`
  range query seams such as `get_range_by_request_id` or `get_active_range`.
  CMS callers must first pass `cms_actor_user` / `HasCMSAuthoringActor` and
  CMS authoring policy. UI hiding is not authorization.
- Serialize a projection, never the raw sidecar row. API responses may expose
  bounded identifiers, record kind, contract version/profile, timestamps,
  status, digests, non-token reference ids, and allow-listed diagnostic refs.
  They must not return `AcesOperationRecord.payload` wholesale.
- Keep output allowlists record-kind specific. Operation receipts, operation
  status, and runtime snapshots have different public fields; do not make a
  generic JSON passthrough serializer that trusts whatever the sidecar accepted.
- Keep legacy non-ACES range behavior stable. Existing range APIs must keep
  working when no ACES sidecar rows exist. If an existing response grows an
  ACES projection field, it must be optional/null and covered by non-ACES
  regression tests; otherwise prefer a dedicated read projection endpoint.
- Use `shared.api.errors` for canonical DRF responses and the
  `MissionControlAPIView` helpers where legacy Mission Control compatibility is
  still in scope. Raw ACES, provider, storage, database, Terraform, SSM, SSH,
  or parser exceptions must not become response messages.
- Log only sanitized identifiers, status names, counts, timings, and diagnostic
  reference ids. Do not log sidecar payloads, snapshots, raw exception text, or
  provider dictionaries from API code.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| Parent ACES operation design | `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md` | Keep sidecar evidence separate from Shifter runtime authority. |
| Sidecar persistence | `shared.models.AcesOperationRecord`, `shared.aces.operations`, `shared.schemas.aces_operation` | Read from the first-class sidecar and its shared helper seam; do not define app-local ACES record schemas. |
| Status projection | `shared.aces.status`, `engine.services.project_aces_operation_status`, `docs/architecture/aces-operation-status-range-event-preflight-1274.md` | Treat mapped Shifter status as an existing projection, not a new API-owned lifecycle. |
| Operation identity | `cms.models.Request.request_id`, `engine.models.Request.request_id`, `cms.services.get_range_by_request_id` | Authorize and correlate by `request_id`; keep `range_id` secondary. |
| Mission Control API base | `mission_control.api._base.MissionControlReadAPIView`, `_range_read_permission`, `_validated`, `MissionControlAPIView.not_found/error_response` | Use the existing permission, validation, and response helpers. |
| Mission Control actor policy | `mission_control.api.permissions.mission_control_actor_user`, `HasMissionControlActor` | Token owners and session users resolve through the same actor path. |
| CMS API policy | `cms.api.permissions.CMS_READ_PERMISSIONS`, `cms_actor_user`, `HasCMSAuthoringActor` | CMS reads continue to require staff or Threat Research authoring access. |
| API token scopes | `shared.api_tokens.scopes`, `shared.api_tokens.permissions.require_scope`, `shared.api_tokens.authentication.ApiTokenAuthentication` | Use exact read scopes; no wildcard, broad `aces:*`, or token-session fallback behavior. |
| DRF errors | `shared.api.errors.api_exception_handler`, `api_error_response` | Keep canonical `{error: {code, message, details?, request_id?}}` responses for `/api/v1`. |
| Safe messages | `shared.errors.safe_user_message`, `classify_user_message` | Convert domain errors to curated user messages; never return raw exception text. |
| Range DTOs | `shared.schemas.RangeContext` and current Mission Control range response shape | Add ACES summaries as optional projections only when needed; do not replace existing range DTOs. |
| Redaction/logging | `shared.log_sanitize.safe_log_value`, `shared.schemas.aces_operation.DIAGNOSTIC_REF_KEYS`, provisioner `log_redact` | Response and log fields stay bounded and reference-only. |
| API routing/schema | `config.api_urls`, `mission_control.api.urls`, `cms.api.urls`, drf-spectacular defaults | Keep routes under versioned API namespaces and OpenAPI generation. |
| Import enforcement | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, `scripts/adr_guard/adr_guard.py` | All app layers may import `shared`; Mission Control reaches CMS through `cms.services`, not CMS models or internals. |

## Cross-Cutting Layers The Design Must Pass

- Session/API-token authentication: requests pass through
  `ApiTokenAuthentication` followed by `SessionAuthentication`. Malformed or
  invalid bearer tokens fail closed and must not fall through to a logged-in
  session.
- API-token scopes: Mission Control projection reads require
  `mission_control:range:read`; CMS authoring projection reads require
  `cms:authoring:read`. If implementation proves a new audience is necessary,
  add one exact scope in `shared.api_tokens.scopes`, update `KNOWN_SCOPES`, and
  add token-access regression tests.
- Product authorization: Mission Control actor resolution uses the token owner
  or session user, then service-layer range ownership checks. CMS actor
  resolution uses active staff or Threat Research authoring policy. Not-owned
  range/request ids should produce the same not-found behavior as existing
  range services, not an enumeration signal.
- Request shape validation: route parameters and query/body inputs use DRF
  serializers, UUID fields, bounded integer limits, and safe enum choices.
  Do not parse UUIDs or record-kind filters with ad hoc string code in views.
- Sidecar contract shape: sidecar rows already passed
  `shared.schemas.aces_operation` for record kind, contract kind/version,
  contract profile, digest, payload size, diagnostic key allowlists, and
  secret-pattern rejection. API code must still apply a response allowlist
  because "safe to persist internally" is not the same as "safe to return."
- Response redaction: responses exclude secrets, credential values, private
  keys, bearer tokens, token-bearing or presigned URLs, prompt bodies,
  generated scripts, command strings, terminal output, raw package bodies, CTF
  flags, provider dumps, Terraform/SSM/SSH output, and unbounded diagnostic
  text. References are single-line ids or digests, not embedded bodies.
- Error envelopes: canonical `/api/v1` errors use `shared.api.errors`.
  Legacy Mission Control compatibility, if touched, uses existing
  `MissionControlAPIView` legacy handling. Raw ACES/provider exceptions are
  sanitized into fixed messages such as "Operation status unavailable."
- Observability: logs use `safe_log_value` for external-ish ids and include
  counts/statuses only. No payload dumps in application logs, request logs,
  test failure snapshots, OpenAPI examples, or audit records.
- Persistence/query boundaries: read helpers should live in `shared.aces` or a
  narrow service facade and return serializer-ready projections. Mission
  Control must not import CMS models directly; CMS/CTF/Mission Control must
  not import ACES SDL packages or provisioner internals.
- OS/process exposure: this read API should not need new subprocesses, shell
  commands, Kubernetes Jobs, workflow steps, or env literals. If diagnostics
  link to external artifacts, expose stored reference ids only; never mint or
  return token-bearing URLs from this projection layer.
- Config/env validators: this slice should not need new runtime knobs. If a
  bounded history limit, default page size, or feature exposure flag becomes
  configurable, add it through Django settings plus `config/env-manifest.json`,
  runtime inventory/rendering, and tests rather than view-local `os.environ`
  reads.
- Whole-repo enforcement: changes touching `shifter/shifter_platform` must pass
  import-linter, layer import checks, DRF settings expectations, API URL/schema
  tests, and ADR guard. Do not weaken those checks for ACES projection work.

## Extensibility Seam

The seam belongs in a shared ACES read-projection helper, not in each view. It
should be parameterized by:

- `request_id` as the correlation key;
- `record_kind` (`operation_receipt`, `operation_status`,
  `runtime_snapshot`, later `execution_plan_ref` only as references);
- `contract_profile` and `contract_version`;
- a bounded result policy such as latest-only versus an explicit small limit;
- a response-field allowlist for the calling product surface.

The next reasonable variation is another backend profile, operation contract
version, or consumer needing a different subset of sanitized fields. That
should add a projection branch and serializer test behind the shared helper,
not copy sidecar queries or redaction rules into Mission Control, CMS, CTF,
templates, or JavaScript.

## Whole-Repo Scope

Future implementation must evaluate changes against:

- `docs/architecture/aces-operation-status-snapshot-projection-preflight-1234.md`
- `docs/architecture/aces-operation-sidecar-persistence-preflight-1273.md`
- `docs/architecture/aces-operation-status-range-event-preflight-1274.md`
- `docs/architecture/aces-migration-adr.md`
- `docs/adr/index.yaml` entries for ADR-024, ADR-025, and ADR-027
- `shifter/shifter_platform/shared/models.py`
- `shifter/shifter_platform/shared/aces/**`
- `shifter/shifter_platform/shared/schemas/aces_operation.py`
- `shifter/shifter_platform/shared/api/**`
- `shifter/shifter_platform/shared/api_tokens/**`
- `shifter/shifter_platform/cms/api/**`
- `shifter/shifter_platform/cms/services/**`
- `shifter/shifter_platform/cms/models/range.py`
- `shifter/shifter_platform/mission_control/api/**`
- `shifter/shifter_platform/config/api_urls.py`
- `shifter/shifter_platform/config/settings.py`
- `shifter/shifter_platform/config/env-manifest.json` only if new settings are
  introduced
- `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/**`, and `.gc/plan-rules.md`

## Regression Evidence Expectations

- Authorized Mission Control reads cover session users and API tokens with
  `MISSION_CONTROL_RANGE_READ`.
- Forbidden cases cover anonymous users, inactive actors, missing token scopes,
  and malformed bearer tokens that must fail closed over any session.
- Not-found cases cover unknown request ids and request ids owned by another
  user without leaking whether the sidecar row exists.
- CMS read cases cover staff/Threat Research authoring access and regular-user
  denial for any CMS projection route.
- Redaction tests seed sidecar rows containing every allowed record kind and
  prove responses exclude raw `payload` passthrough, secrets, prompt/script
  fields, token-bearing refs, provider dumps, flags, package bodies, and
  unbounded diagnostic text.
- Legacy non-ACES range tests prove current Mission Control range behavior
  remains unchanged when no ACES sidecar rows exist.
- Schema/tests cover OpenAPI exposure, exact scopes, response shapes, canonical
  error envelopes, and bounded history/page-size behavior if history is
  exposed.

## Gotchas And Anti-Patterns

- Do not add an `/api/v1/aces/` namespace, ACES-only token audience, wildcard
  scope, exception hierarchy, response envelope, status enum, websocket topic,
  or audit table for this read projection.
- Do not authorize by checking for a visible UI element, scenario entry, or
  sidecar row. Authorize through session/token gates and product service-layer
  ownership/authoring checks first.
- Do not expose `AcesOperationRecord.payload` as JSON just because the sidecar
  validator accepted it. The API needs its own public-field allowlist.
- Do not treat `diagnostic_refs` as safe if a value is a presigned URL, bearer
  URL, command, prompt, transcript, provider dump, or embedded log. Return a
  stable reference id/fingerprint instead.
- Do not make `range_id` the lookup key for operation APIs. It is useful for
  display and backfill but not reliable as the ACES operation identity.
- Do not duplicate ACES contract schemas, operation-state mappings, ownership
  checks, validation helpers, serializer logic, or error wrappers in each view.
- Do not make read APIs perform cleanup, projection writes, event enqueueing,
  status reconciliation, artifact fetches, external provider calls, or URL
  signing.
- Do not weaken ADR guard, import-linter, secret scanning, API-token scope
  validation, DRF error handling, or existing non-ACES range behavior to make
  ACES projections easier to expose.

## Non-Goals

- No API implementation in this preflight note.
- No mutation endpoints, sidecar writes, status projection writes, event
  enqueueing, websocket changes, cleanup jobs, or UI changes.
- No replacement of `engine.Range`, `cms.RangeInstance`, `ResourceStatus`,
  `RangeEventOutbox`, Mission Control range UX, CMS authoring policy, or CTF
  range workflows.
- No raw ACES package/source exposure, execution-plan bodies, transcripts,
  prompts, generated scripts, provider dumps, token-bearing URLs, or experiment
  evidence archive.
- No new Ground Control requirement UID for this requirement-free run.
- No changelog fragment for this docs-only preflight note.

## Validation Expectations

For this design-doc change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future runtime implementation touching `shifter/shifter_platform` should also
run the Mission Control API-token tests, CMS API-token tests, shared API error
tests, ACES sidecar/projection tests, import-linter checks, and any changed
subsystem tests required by `AGENTS.md` and `.gc/plan-rules.md`.
