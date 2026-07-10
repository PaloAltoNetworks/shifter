# CMS/CTF Range Source Preflight (#450)

Status: pre-implementation guidance

Date: 2026-06-29

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/450>

This note is intentionally not an implementation plan. Issue #450 is
requirement-free; the GitHub issue is the contract. The upcoming change should
allow a user to hold one Mission Control range and one CTF participant range at
the same time while preserving the existing CMS, CTF, Mission Control, and
Engine boundaries.

## Scope Boundary

The bug is in the CMS active-range admission check:
`cms.services.create_range()` calls `get_active_range(user)`, and that query is
currently scoped only by `RangeInstance.user_id` plus active lifecycle state.
The fix should make "already has an active range" a per-range-source constraint,
not a global per-user constraint.

This is not a CTF scheduler rewrite, a new RBAC model, a Mission Control UI
redesign, an Engine provisioner change, or a replacement for request-id and
range-instance identity contracts.

## Architecture Decisions And Guardrails

- The durable discriminator belongs in CMS range persistence. Use a CMS-owned
  range provenance field on `RangeInstance` or a CMS-owned equivalent; do not
  infer provenance from `scenario_id`, CTF event data, task metadata, template
  structure, user groups, or the caller module name.
- Name the concept as range provenance, such as `range_source`, not generic
  `source` if that would be confused with `CTFScheduledTask.metadata["source"]`
  (`manual` versus scheduled enqueue provenance).
- Mission Control and CTF are the initial provenance values. Existing rows
  should keep current Mission Control semantics unless the row was explicitly
  created through a CTF path that can be proven during migration.
- The active-range limit is per `(user_id, range_source)` over non-soft-deleted,
  non-DESTROYING rows. Reuse `RangeInstance.objects`, `ResourceStatus`, and the
  existing soft-delete invariant; do not hand-roll deleted-row filters or a new
  lifecycle vocabulary.
- CTF must set range provenance only through `ctf.bridges.cms_create_range` and
  the public `cms.services` facade. CTF views/services must not import CMS models
  or Engine internals to work around the active-range check.
- Mission Control launch/current-range/sidebar behavior should continue to mean
  Mission Control range unless an explicit server-derived range source is passed.
  Do not let a request body, query param, or JavaScript select the source.
- `RangeContext` is still a projection of a CMS range, not the source-of-truth
  schema for provenance. Add provenance to shared DTOs only if a caller must
  display or authorize from it; otherwise keep the discriminator in persistence
  and service parameters.
- Audit the Engine terminal/Guacamole assumption before declaring both ranges
  fully usable. `engine.models.Range.get_active_for_user()` and terminal helpers
  still choose a single active Engine range for a user. A CMS-only source filter
  can make provisioning succeed while later RDP/SSH access resolves the wrong
  active Engine range.
- Same-source concurrent creation is still a race if admission remains only a
  read-before-create check. Do not claim stronger concurrency guarantees unless
  the implementation adds a compatible lock or database constraint and tests it.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #450 |
| --- | --- | --- |
| CMS range persistence | `cms.models.RangeInstance`, `Request`, `SoftDeleteManager`, `SoftDeleteQuerySet` | Extend the existing row; do not add a second range table or repository. |
| CMS active range queries | `cms.services.get_active_range`, `has_ready_active_range`, `_validate_caller_user` | Parameterize provenance at this seam and preserve user validation, FK eager loading, runtime-IP overlay, and cheap-sidebar semantics. |
| CMS range creation | `cms.services.create_range`, `_assert_no_active_range`, `_persist_range_instance_record` | Keep scenario, agent, request, engine dispatch, failure rollback, and audit behavior in the existing create flow. |
| Status vocabulary | `shared.enums.ResourceStatus` | Reuse existing active/terminal/destroying values; do not introduce duplicate status strings. |
| CTF boundary | `ctf.bridges.cms_create_range`, `cms_find_range_instance_id`, `ctf.services.range.provision_participant_range` | Pass server-derived CTF provenance through the bridge and keep participant locking/assignment behavior intact. |
| CTF identity | `CTFParticipant.range_instance_id` | This remains a CMS `RangeInstance.pk`, not an Engine `Range.id`, request id, event id, or provenance value. |
| Mission Control auth/API | `MissionControlAPIView`, `LaunchRangeSerializer`, `_range_write_permission`, `block_participant_lifecycle_permission` | Preserve auth, scopes, participant-only blocking, serializers, and authored error responses. |
| Engine access | `Range.get_active_for_user`, `get_rdp_connection_info`, `get_ssh_connection_info` | Either keep access paths tied to the intended range or make the single-active assumption explicit; do not silently rely on first active row order. |
| Error and logging hygiene | `CMSError`, `CTFRangeError`, `shared.errors.classify_user_message`, `shared.log_sanitize.safe_log_value` | Preserve ownership masking and authored client messages; log source as a low-cardinality label only. |
| Tests | `tests/cms/test_services.py`, `tests/cms/test_services_range.py`, `tests/ctf/test_services/test_range.py`, Mission Control range/API tests | Use DB-backed CMS behavior tests and CTF bridge-seam tests; do not add detached topology tests. |

## Cross-Cutting Layers

- Auth surface: Mission Control launch still passes session/API-token auth,
  actor resolution, range-write scope, and participant-only lifecycle blocking.
  CTF provisioning still passes organizer/event service authorization before it
  reaches the CMS bridge. The range source is server-derived after those gates.
- Validation surface: reuse DRF serializers for request bodies, CMS user/scenario
  and agent validators, `ResourceStatus` validation, and Pydantic `RangeContext`
  creation. Do not accept a user-supplied source string.
- Persistence surface: CMS owns `Request` and `RangeInstance`; CTF owns
  `CTFParticipant.range_instance_id`; Engine owns runtime `Range` rows. Keep
  `RangeInstance.pk`, `RangeInstance.range_id`, Engine `Range.id`, and
  `Request.request_id` distinct.
- Import-boundary surface: `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`, and `adr_guard` require CTF
  to cross into CMS through `cms.services`, Mission Control not to import CTF,
  and Engine not to depend on CMS/Mission Control/CTF.
- Secret-handling surface: this flow should not create or expose secrets. Do not
  log or return invite tokens, API tokens, cookies, CSRF tokens, flags, SSH keys,
  RDP passwords, Guacamole signed URLs, presigned URLs, provider payloads, or env
  dumps.
- Config and OS/runtime exposure: no new setting, env var, management command,
  shell argv, scheduler process, Terraform value, or Kubernetes binding is needed
  for #450. If one appears, the design has likely left scope.
- Error-envelope surface: MC legacy routes keep flat authored errors, canonical
  APIs use shared API envelopes, and CTF wraps CMS failures in `CTFRangeError`.
  Do not expose another user's source-specific range existence.
- Observability surface: useful labels are `user_id`, `request_id`,
  `range_instance_pk`, `range_source`, status, and CTF participant/event ids.
  Keep values sanitized and low-cardinality.

## Extensibility Seam

The durable seam is a server-derived `range_source` parameter at CMS range create
and active-range query boundaries, persisted on `RangeInstance`.

That seam lets future sources such as experiments, post-deploy smoke ranges, or
training labs opt into their own per-source admission policy without reusing CTF
metadata, editing scenario templates, or widening Mission Control/CTF imports.
If future terminal access must target a specific simultaneous range, the seam is
request id or `RangeInstance.pk`, not a global "active range for user" lookup.

## Gotchas And Anti-Patterns

- Do not filter by `scenario_id`; Mission Control and CTF can use the same
  scenario.
- Do not use user groups to infer range provenance; organizers and participants
  can also be Mission Control users.
- Do not confuse CTF scheduled-task `source=manual` with CMS range provenance.
- Do not add CTF-specific imports to Mission Control or CMS.
- Do not add a second exception hierarchy, logging sanitizer, DTO, workflow
  queue, or range lifecycle state machine.
- Do not weaken the existing "same source already has active range" behavior.
- Do not let CTF bulk provisioning bypass CMS scenario/agent validation,
  request creation, engine dispatch, or failure status handling.
- Do not mark the issue complete with only a successful create test if terminal,
  Guacamole, or status paths now resolve an unintended active Engine range.

## Non-Goals

- No implementation is performed by this preflight.
- No formal Ground Control requirement or traceability change is attached.
- No new public API, RBAC rule, CTF event schema, scenario DSL field, Engine
  provisioner contract, scheduler task type, or runtime config knob is required.
- No broad migration of existing CTF participant linkage away from
  `CTFParticipant.range_instance_id`.
- No weakening of ADR guard, import-linter, CodeQL/error-envelope safeguards,
  secret scanning, or runtime health checks.

## Validation Expectations

Architecture or `shifter/shifter_platform` changes on this path must pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups that touch Python under `shifter/shifter_platform`
should also run the focused CMS range service tests, CTF range provisioning
tests, relevant Mission Control range/API tests, ruff, and import-linter when
imports change.
