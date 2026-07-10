# CTF Per-Event Instance Visibility Preflight (#539 / CTF-906)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-906` - Per-Event Instance Visibility

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. The upcoming work should
close the CTF-906 evidence gap with meaningful automated coverage and Ground
Control `TESTS` traceability while preserving the existing CTF, CMS, Mission
Control, and Engine boundaries.

## Scope Boundary

CTF-906 has three visibility contracts:

- a participant sees only the range associated with the participant row for the
  user's active CTF event;
- Event A and Event B remain isolated even when both events use the same
  `scenario_id` and create ranges for the same Django user;
- Mission Control range listings and launch/lifecycle affordances exclude
  CTF-only participant ranges unless the account also has a Mission Control
  role that grants normal range access.

This is not a CTF range-provisioning rewrite, a Mission Control UI redesign, a
new RBAC model, or a replacement for Engine's active-range/instance-UUID access
checks.

## Architecture Decisions And Guardrails

- Event visibility is CTF-owned. The event source of truth is
  `UserProfile.active_ctf_event_id` resolved through `ctf.bridges.get_user_role`
  and `ctf.services.participant.get_participant_by_user(user, event_id=...)`.
  Do not resolve participant range state through an unscoped "first participant"
  query.
- Participant range linkage uses `CTFParticipant.range_instance_id` as a CMS
  `RangeInstance` primary key. Do not treat it as an Engine `Range.id`, a
  `request_id`, or a scenario identifier.
- Scenario identity is not a visibility boundary. Event A and Event B may share
  the same scenario template, range spec, OS mix, and instance roles; filtering
  by `scenario_id`, `os_type`, role, or instance name cannot satisfy CTF-906.
- Mission Control may enforce role-based visibility using `shared.auth`
  predicates, but it must not import `ctf` or query CTF models directly. If a
  durable provenance marker is needed so Mission Control/CMS can distinguish CTF
  ranges from normal ranges, extend the existing CMS range persistence/service
  surface narrowly and set it through the CTF-to-CMS bridge. Do not infer CTF
  ownership from scenario names or template structure.
- Keep CTF-to-CMS calls behind `ctf.bridges` and `cms.services`. CTF views and
  services must not import Engine models or Mission Control internals to compute
  visibility.
- Keep lower-level access gates intact. Engine and Guacamole still enforce
  active range, `READY` status, instance UUID membership, GUI/SSH capability,
  and credential availability; CTF must ensure the exposed active range is the
  participant's active-event range before those gates run.
- Template hiding is not authorization. Launch, cancel, destroy, pause, and
  resume stay blocked server-side for participant-only accounts through
  `shared.auth.block_ctf_participant_only` and the DRF equivalent in
  `mission_control.api.permissions`.
- Ground Control `TESTS` links for CTF-906 must point at maintained tests that
  prove cross-event isolation and Mission Control filtering. Do not link this
  note, audit docs, fixtures, or broad smoke tests that do not exercise the
  event/range visibility contract.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-906 |
| --- | --- | --- |
| CTF role and active event | `ctf.bridges.get_user_role`, `management.services.set_active_ctf_event`, `UserProfile.active_ctf_event_id` | Active event is server-derived; do not accept event selection from query string, POST body, or JavaScript for participant-owned range visibility. |
| Participant eligibility and event scoping | `ctf.services.participant.eligible_participant_q`, `is_active_participant`, `get_participant_by_user(user, event_id=...)` | Preserve disqualified-participant exclusion and always pass event scope on event-, challenge-, range-, and active-event-specific surfaces. |
| Organizer ownership | `ctf.views.api._common._resolve_owned_event_json`, `ctf.services.authorization.assert_actor_owns_event` | Organizer range list/actions still prove event owner; scopes or CTF Organizer group membership do not grant all events. |
| CTF range services | `ctf.services.range`, `ctf.bridges.cms_*` | Use the range service facade and CMS bridge; do not call CMS/Engine internals from CTF views or tests. |
| CMS range identity | `cms.models.RangeInstance`, `cms.services.find_range_instance_id_by_request`, `get_range_status_by_id`, `get_range_spec_by_id` | Keep `RangeInstance.pk`, `RangeInstance.range_id`, and `request_id` distinct. |
| Active range projection | `cms.services.get_active_range`, `has_ready_active_range`, `get_range_by_request_id`, `shared.schemas.RangeContext` / `InstanceContext` | Reuse DTO validation and user ownership; do not create a parallel range DTO or return raw model rows to templates. |
| Mission Control role filter | `shared.auth.is_ctf_participant_only`, `PARTICIPANT_ALLOWED_LIFECYCLE_VERBS`, `block_ctf_participant_only`, `mission_control.api.permissions.block_participant_lifecycle_permission` | Keep participant-only filtering and lifecycle denial in shared auth policy, not only in templates. |
| Guacamole and terminal access | `mission_control.api.guacamole`, `mission_control.views._guacamole`, `engine.services.get_rdp_connection_info`, `get_ssh_connection_info` | Preserve active-range and instance-UUID checks; do not bypass them with CTF-specific signed URLs. |
| API scopes and envelopes | `ctf.api._base`, `shared.api_tokens.scopes`, `shared.api.errors` | Canonical `/api/v1/ctf/` coverage must preserve scope admission plus domain authorization and shared error envelopes. |
| Errors and logging | `ctf.exceptions`, `shared.errors.classify_user_message`, `shared.api.errors`, `shared.log_sanitize.safe_log_value` | Return authored `403`/`404`/`400` messages; log sanitized identifiers and keep raw exceptions server-side. |
| Tests | `tests/ctf/test_mid_event_operations.py`, `tests/mission_control/test_context_processors.py`, `tests/mission_control/test_range_api.py`, `tests/ctf/test_drf_api_token_access.py`, `tests/cms/test_services_range.py` | Strengthen existing behavior suites with DB-backed cross-event cases instead of adding detached placeholder tests. |

## Cross-Cutting Layers

- Auth surface: participant HTML/API routes stay behind `@login_required`,
  `@ctf_participant_required`, or `CTF_PARTICIPANT_PERMISSIONS`. Organizer range
  APIs stay behind `@ctf_organizer_required` or `CTF_ORGANIZER_PERMISSIONS` plus
  event ownership. Mission Control routes keep session/API-token authentication
  and participant-only lifecycle blocking.
- Token scope surface: `/api/v1/ctf/` token requests require the existing CTF
  scopes (`ctf:play:read`, `ctf:play:write`, `ctf:event:read`,
  `ctf:event:write`) before domain checks. Scopes are admission only and must
  not bypass event ownership or participant active-event resolution.
- Validation surface: URL UUIDs, JSON bodies, and query params use existing
  parsing helpers or DRF serializers. Domain validation stays in CTF services,
  CMS service validators, and Pydantic/shared range schemas.
- Persistence surface: `CTFParticipant` owns event membership and stores the CMS
  `RangeInstance` PK. CMS owns `RangeInstance`, `Request`, `RangeContext`, and
  user ownership. Engine owns runtime `Range` state and provisioned instance
  membership. Keep these IDs and ownership checks explicit.
- Import-boundary surface: CTF crosses into CMS only through `ctf.bridges` and
  `cms.services`; Mission Control relies on shared auth/CMS services and must
  not import CTF; CMS must not import presentation layers; Engine remains below
  CMS/Mission Control.
- Error-envelope surface: legacy CTF routes return controlled flat
  `{"error": "..."}` payloads; canonical API routes use `shared.api.errors`.
  Ownership misses should not reveal other users' or other events' range IDs.
- Secret-handling surface: this flow should not expose secrets. Do not log,
  return, snapshot, or place in process argv: invite tokens, API tokens, cookies,
  CSRF tokens, submitted flags, range credentials, SSH keys, RDP passwords,
  Guacamole signed URLs, presigned URLs, cloud provider payloads, or environment
  dumps.
- OS/runtime exposure: no new runtime process or shell command should be needed.
  If a follow-up adds a setting or env binding, use existing `config.settings`
  parsers and avoid putting user/event/range identifiers or secrets on command
  lines.
- Observability surface: useful logs are event id, participant id, range
  instance PK, request id, aggregate counts, status, and denial reason class.
  Sanitize user-controlled values and keep labels low-cardinality.

## Extensibility Seam

The durable seam is a server-derived visibility context:

- actor: session user or API-token owner;
- role: CTF participant, CTF organizer, participant-only, or Mission
  Control-capable user from `shared.auth` / `ctf.bridges`;
- CTF scope: active event id and participant id from
  `get_participant_by_user(user, event_id=active_event_id)`;
- range reference: CMS `RangeInstance.pk`, with `request_id` only for request
  correlation and lifecycle APIs;
- view depth: Mission Control normal listing versus CTF participant range view.

That seam lets future work support event switching, team-owned ranges, multiple
range types, or richer Mission Control users without changing Engine terminal
authorization, duplicating CTF participant queries, or making scenario templates
carry visibility policy.

## Gotchas And Anti-Patterns

- Do not use `Range.get_active_for_user(user)` or `cms.services.get_active_range`
  alone as proof of CTF event visibility. They prove user ownership, not event
  membership.
- Do not use `scenario_id` as a proxy for CTF event ownership.
- Do not confuse CMS `RangeInstance.pk`, legacy nullable
  `RangeInstance.range_id`, Engine `Range.id`, and CMS `Request.request_id`.
- Do not mutate a shared `RangeContext.instances` list in a way that can leak a
  filtered CTF projection into another consumer.
- Do not add CTF-specific imports to Mission Control to filter dashboard state.
- Do not add a duplicate participant-range schema, exception hierarchy, logging
  sanitizer, API-token scope registry, or workflow queue.
- Do not satisfy the requirement with template-only checks, front-end filtering,
  broad role checks, or tests that use only one event.
- Do not expose other-event existence through distinguishable response text,
  stack traces, task error messages, or raw `CTFError.details` payloads.

## Non-Goals

- No requirement implementation is performed by this preflight.
- No new public API, RBAC model, scheduler framework, range lifecycle model,
  scenario schema, Engine access-control rewrite, or Guacamole URL scheme.
- No broad CTF range provisioning, CTFd integration, scoring, notification,
  invite-token, or scheduler remediation.
- No Ground Control `IMPLEMENTS` trace changes are required for this preflight;
  the follow-up should reconcile a `TESTS` link only after maintained tests
  prove CTF-906.

## Validation Expectations

Architecture or `shifter/shifter_platform` changes on this path must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups that touch Python under `shifter/shifter_platform`
should also run the relevant CTF participant/range/API tests, Mission Control
context and lifecycle tests, canonical DRF API-token tests, ruff, and
import-linter when imports change.
