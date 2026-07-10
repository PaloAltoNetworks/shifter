# CTF-013 Admin Analytics Preflight (#539)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: CTF-013, Administration

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

## Scope Boundary

CTF-013 is the organizer visibility requirement for CTF events. The current
work driven by issue #539 is evidence and correctness work for the existing
organizer dashboards, analytics, scoreboard, event detail, and range overview
surfaces. It is not a request to create a second Mission Control product area,
a separate analytics warehouse, a new reporting API, or a new authorization
model.

The relevant runtime surfaces are the existing CTF organizer views:

- `ctf.views.admin_dashboard`
- `ctf.views.admin_event_detail`
- `ctf.views.admin_analytics`
- `ctf.views.admin_scoreboard`
- `ctf.views.admin_range_list`

The relevant evidence surface is Ground Control: CTF-013 must have at least one
meaningful `TESTS` trace link to maintained automated tests. Placeholder tests
or links to broad test files that do not assert organizer operational visibility
do not satisfy the requirement.

## Architecture Decisions

- Organizer visibility remains a CTF service-backed HTML surface rendered in
  Mission Control's UI shell and templates. Do not move CTF admin analytics into
  Mission Control models, views, or services.
- The CTF service layer owns event statistics, challenge statistics, scoreboard
  reads, participant eligibility, range status aggregation, and event lifecycle
  state. Views compose those service contracts and enforce HTTP access.
- The authoritative statistics source remains the CTF database models:
  `CTFEvent`, `CTFParticipant`, `CTFChallenge`, `CTFSubmission`, `CTFAward`,
  `CTFTeam`, and `CTFBracket`. Derived leaderboard columns are allowed only
  through the existing scoring maintenance contract and must stay rebuildable
  from submissions and awards.
- Organizer access is event-owner scoped. Group membership proves that a user is
  a CTF organizer; it does not grant access to every event.
- Tests for CTF-013 should prove meaningful behavior across the existing
  boundaries: organizer-only access, owner scoping, dashboard/event statistics,
  challenge analytics, scoreboard mode and bracket behavior where relevant, and
  range-health visibility. They should not patch away the CTF service contract
  that the requirement is meant to prove.
- Ground Control traceability is the source of truth for requirement evidence.
  Do not add a repo-local traceability file or duplicate requirement registry.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-013 |
| --- | --- | --- |
| Browser auth | Django `@login_required` plus `ctf.views._access.ctf_organizer_required` | Keep organizer views behind the existing session auth and CTF organizer gate. Do not add bypass decorators, staff-only substitutes, or template-only hiding. |
| Role source | `ctf.bridges.get_user_role`, `shared.auth.CTF_ORGANIZER_GROUP`, `shared.auth.get_user_group_names` | Use the existing group/profile bridge. Do not re-query groups differently in views or tests. |
| Event ownership | `event.created_by_id`, `_check_event_ownership`, `_resolve_owned_event_json`, and service-layer `assert_actor_owns_event` for mutators | A CTF organizer may inspect only owned events unless a later requirement changes the policy. |
| Admin routes | `ctf.urls.admin_patterns` | Reuse the existing route names and URL shape under `/ctf/admin/...`; do not create parallel Mission Control URLs for the same CTF pages. |
| Admin templates | `templates/ctf/admin/*.html`, `templates/ctf/includes/admin_scoreboard_rows.html`, and `templates/ctf/base.html` | Keep the UI in the established CTF template family and Mission Control shell. |
| Event counts | `ctf.services.event.get_event_stats` | Do not duplicate participant/challenge/submission counts in templates or ad hoc test helpers. |
| Analytics | `ctf.services.scoring.get_event_statistics` and `get_challenge_statistics` | Fix or assert analytics in the service layer, then render them through the admin view. |
| Scoreboard | `ctf.services.scoring.get_scoreboard`, `get_team_scoreboard`, materialized leaderboard maintenance, and `eligible_participant_q` | Preserve individual/team, bracket, freeze, visibility, and eligibility semantics. |
| Range visibility | `ctf.services.range.get_provision_progress`, participant `range_status`, and `ctf.bridges` CMS adapters | Do not call CMS or engine directly from admin views or templates. |
| CTF exceptions | `ctf.exceptions.CTFError` subclasses | Reuse the CTF exception hierarchy. Do not add local analytics/range/reporting exception classes. |
| JSON/API envelope | `ctf.views._access._json_error`, `ctf.api._base.CTFLegacyAPIView`, `shared.api.errors.api_error_response` | If API evidence is added, keep the shared DRF envelope and legacy CTF flat-error conversion. |
| Logging | Module loggers plus `shared.log_sanitize.safe_log_value` / `safe_log_fingerprint` | Log event IDs and bounded status/count details only. Do not log flags, invite tokens, cookies, CSRF tokens, or raw exception payloads. |
| Tests | `tests/ctf/conftest.py`, `tests/ctf/factories.py`, `tests/ctf/test_organizer_access.py`, `tests/ctf/test_events.py`, `tests/ctf/test_scoring_statistics.py`, and `tests/test_test_suite_structure.py` | Use existing fixtures and behavior-scoped test modules. Avoid oversized all-in-one CTF-013 tests. |
| Architecture gates | `.importlinter`, `scripts/adr_guard/adr_guard.py`, `.ground-control.yaml`, `.gc/plan-rules.md` | Keep CTF isolated from `engine` and `mission_control`; route cross-domain calls through `ctf.bridges` and `shared`. |

## Cross-Cutting Layers

- Auth surface: organizer HTML views must pass Django session auth,
  `@login_required`, `ctf_organizer_required`, `get_user_role`, and
  event-owner checks. DRF/API paths, if used as evidence, must also pass
  `IsAuthenticatedSessionOrApiToken`, `HasActiveCTFActor`,
  `HasCTFEndpointScope`, and `HasCTFOrganizer`.
- Request validation surface: admin HTML analytics currently read route UUIDs
  and optional query parameters such as `bracket`. Route UUID conversion stays
  in Django URL routing, and bracket filtering stays in
  `_resolve_bracket_filter`. JSON write/read-adjacent API tests must keep
  `_parse_body_object`, `_get_body_str`, `_parse_body_uuid`, and the DRF
  `JSONBodySerializer` shape gate.
- Domain policy surface: statistics and scoreboards must use event-scoped
  participants, `eligible_participant_q`, challenge/event relationships,
  team/bracket membership, scoreboard freeze, hidden-scoreboard behavior, and
  active/disqualified participant rules. A test that asserts raw row counts
  while bypassing those policies is not requirement evidence.
- Secret-handling surface: submitted flags, flag hashes, challenge solutions,
  invite tokens, session cookies, CSRF tokens, API tokens, CMS range IDs when
  security-sensitive, and validator configuration must not be emitted in logs,
  test failure snapshots, process argv, screenshots, GitHub comments, or
  Ground Control reports.
- Config and env-binding surface: CTF-013 should not introduce environment
  variables, Terraform variables, Kubernetes values, or Django settings. If a
  future reporting refresh interval, analytics limit, or visibility toggle is
  required, it belongs in the event-owned model/form/API validation surface, not
  in process-global config.
- Error-envelope surface: HTML views should continue to return controlled
  `Http404` or authored 403 bodies for missing or unauthorized events. JSON API
  evidence must use controlled `{"error": ...}` legacy responses or the shared
  DRF envelope. Do not return `str(exc)`, SQL, stack traces, raw provider
  errors, or ownership internals.
- Persistence surface: reads must remain ORM-backed and source from CTF models
  or the existing materialized leaderboard contract. Do not add an analytics
  table, cache-only statistics, local files, or a separate repository layer for
  this requirement.
- Cross-domain boundary: range health data crosses from CTF to CMS through
  `ctf.bridges` and `ctf.services.range`. CTF admin views must not import
  `engine` or `mission_control` directly; `.importlinter` enforces that
  boundary.
- OS/runtime exposure: this work should stay inside Django, pytest, Ground
  Control, and GitHub API operations. It should not shell out with secrets,
  pass tokens in command-line arguments, write raw event exports to `/tmp`, or
  depend on process-local memory for correctness.

## Extensibility Seam

The durable seam is an event-scoped organizer analytics read model expressed by
parameters, not a new abstraction:

- event id
- viewer user id and organizer ownership
- board type: individual or team
- optional bracket id
- optional freeze cutoff for participant-visible scoreboards
- event status and time window
- participant eligibility status
- range status bucket
- optional display limits for dashboard summaries

Future additions such as per-bracket analytics, category difficulty summaries,
time-windowed submission trends, or range-health rollups should extend the CTF
statistics service contract with explicit parameters and tests. They should not
fork the dashboard query logic, create a second scoreboard schema, or move CTF
analytics into Mission Control.

## Whole-Repo Scope

In scope for future implementation and verification:

- `shifter/shifter_platform/ctf/views/admin_events.py`
- `shifter/shifter_platform/ctf/views/admin_people.py`
- `shifter/shifter_platform/ctf/views/_access.py`
- `shifter/shifter_platform/ctf/views/_parsing.py`
- `shifter/shifter_platform/ctf/services/event.py`
- `shifter/shifter_platform/ctf/services/scoring/_stats.py`
- `shifter/shifter_platform/ctf/services/scoring/_read.py`
- `shifter/shifter_platform/ctf/services/range/*`
- `shifter/shifter_platform/ctf/services/participant/*`
- `shifter/shifter_platform/ctf/bridges.py`
- `shifter/shifter_platform/ctf/models/*`
- `shifter/shifter_platform/templates/ctf/admin/*.html`
- `shifter/shifter_platform/templates/ctf/includes/admin_scoreboard_rows.html`
- `shifter/shifter_platform/tests/ctf/*`
- `.importlinter`
- `scripts/adr_guard/adr_guard.py`
- `.ground-control.yaml`
- `.gc/plan-rules.md`
- Ground Control traceability for the CTF-013 `TESTS` link

Out of scope unless a later accepted requirement explicitly asks for it:
Mission Control service/model changes, engine imports, Terraform/Kubernetes
changes, a new reporting database, a new API token scope family, a new exception
hierarchy, a new DTO/schema layer, and ADR registry changes.

## Gotchas

- The audit notes for CTF-013 predate later changes; use them as gap context,
  then verify against the current split `ctf.views.*` and `ctf.services.*`
  modules rather than the old monolithic `ctf/views.py` paths.
- Challenge solve rate is a requirement-sensitive metric. If it is corrected,
  use a denominator that matches the intended event population and preserve the
  service contract that renders analytics.
- Scoreboard evidence must account for individual mode, team mode, bracket
  filtering, frozen participant boards, hidden participant boards, and organizer
  bypass of participant visibility restrictions.
- `admin_range_list` computes `active_provisioning` from
  `get_provision_progress`, while dashboard range summaries aggregate participant
  `range_status`. Do not conflate "current provision task is active" with "how
  many participant ranges are healthy".
- CTF organizers are not automatically platform superusers. Tests should include
  non-owner organizers and ordinary non-organizer users where access matters.
- Mock-heavy tests can prove branch behavior, but CTF-013 needs at least some
  persisted ORM behavior so counts, relationships, templates, and ownership are
  not only asserted against mocks.
- Ground Control trace links should point to stable behavior-scoped tests. A
  link to a large generic test module is weak evidence if the CTF-013 behavior
  is incidental.

## Anti-Patterns

- Duplicating analytics calculations in templates, admin views, or test helpers.
- Querying Mission Control, CMS, or engine models directly from CTF admin views.
- Adding a second role check, event-owner policy, exception hierarchy, JSON
  envelope, schema registry, or repository layer.
- Treating dashboard cards, scoreboard rows, challenge analytics, and range
  provisioning state as one generic "stats" concept without named contracts.
- Returning raw exceptions or internal IDs in organizer-facing error bodies.
- Logging submitted flags, invite tokens, cookies, CSRF tokens, API tokens,
  validator payloads, SQL, stack traces, or raw provider/CMS errors.
- Using process-local cache, local files, management commands, or background
  jobs as the source of truth for organizer analytics.
- Weakening `.importlinter`, ADR guard, CSRF, session auth, API-token scope
  validation, or Ground Control traceability rules to make coverage easier.

## Non-Goals

- No implementation of CTF-013 behavior in this preflight.
- No migration of CTF admin views into Mission Control.
- No new reporting database, analytics warehouse, cache framework, queue,
  websocket, API surface, serializer family, DTO layer, or exception hierarchy.
- No changes to CTFd synchronization, challenge authoring, hint scoring, range
  provisioning mechanics, scheduled task execution, or platform infrastructure.
- No new Ground Control requirement; CTF-013 is the active requirement and issue
  #539 is the traceability-remediation driver.
- No ADR registry update unless future implementation changes enforceable
  architecture policy or guardrail files.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Future implementation that touches `shifter/shifter_platform` should also run
the relevant focused pytest target(s) and stack-native checks required by
`AGENTS.md`.
