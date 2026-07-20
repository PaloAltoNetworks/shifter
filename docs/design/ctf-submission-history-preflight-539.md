# CTF Submission History Preflight - Issue 539 / CTF-1305

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: CTF-1305, "Submission History"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note records the architecture boundary for closing the submission-history
behavior and traceability gaps. It is intentionally not an implementation plan.

## Boundary

The durable submission ledger already exists:

- `ctf.models.CTFSubmission`
- `ctf.services.submission.submit_flag`
- `ctf.services.submission.get_participant_submissions`
- `ctf.services.submission.get_challenge_submissions`
- `ctf.services.submission.get_correct_submissions`
- `ctf.admin.CTFSubmissionAdmin`
- participant `challenge_detail` and `api_submissions`
- organizer `admin_participant_detail` and `admin_challenge_detail`

The remaining design work is read-side completion and verification: event-wide
organizer search/filter, explicit participant self-view configurability, and
meaningful automated tests with Ground Control `TESTS` links. Do not create a
second submission model, audit table, activity-feed schema, exception hierarchy,
or parallel JSON contract to satisfy this requirement.

## Architecture Decisions

- `CTFSubmission` remains the authoritative record for submitted flag attempts.
  Correctness, submitted value, timestamp, attempt number, points, participant,
  challenge, and source IP belong there; scoring and analytics keep deriving
  from that ledger.
- `submit_flag` remains the only flag-attempt write path. It owns challenge
  availability, attempt limits, cooldown, concurrency locking, correct-solve
  uniqueness, audit IP capture, and scoring side effects.
- Rejected requests from availability, already-solved, attempt-limit, cooldown,
  malformed body, or permission checks are not submission attempts and must not
  create `CTFSubmission` rows.
- Organizer event-wide history is an event-owned read surface. It must scope
  every query to an organizer-owned event before applying correctness,
  participant, challenge, time, and text-search filters.
- Participant history is a participant-owned read surface. It must resolve the
  participant through the existing active-event or challenge-event helpers and
  then check the event's participant-history visibility policy before exposing
  submitted values.
- If participant self-view configurability requires a new field, make it an
  event-owned CTF configuration beside `scoreboard_visible` and
  `rating_visibility`. Wire the same field through the model, event form,
  event service allowlist, event API payload, admin event template, and tests.
- Full-text search is a bounded query feature, not a raw SQL escape hatch. Use
  structured ORM filters over participant name/email, challenge name, and
  submitted flag values.
- Large event histories must be paginated or otherwise bounded. Do not return
  all submissions for a large event from an organizer API or template by
  default.
- Django admin is useful for staff/admin inspection, but it is not a substitute
  for organizer-owned event scoping. Staff `CTFSubmissionAdmin` and organizer
  event UI/API must keep their authorization models separate.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Submission persistence | `CTFSubmission`, `CTFBaseModel` soft-delete managers, existing indexes | Keep one ledger. Choose default manager vs `all_objects` deliberately; participant surfaces must not leak soft-deleted rows accidentally. |
| Submission write policy | `ctf.services.submission.submit_flag` | Do not persist attempts from views, templates, JavaScript, admin actions, middleware, or a new API serializer. |
| Participant access | `@login_required`, `@ctf_participant_required`, `_get_active_participant`, `_get_participant_for_challenge`, `ctf.services.participant.is_active_participant` | Preserve active, non-disqualified, event-scoped participant resolution. |
| Organizer access | `@ctf_organizer_required`, `_check_event_ownership`, `_resolve_owned_participant`, `ctf.services.authorization.assert_actor_owns_event` | Event read scope and organizer role do not authorize another organizer's event. |
| Canonical CTF API | `ctf.api._base.legacy_api_view`, `CTF_PARTICIPANT_PERMISSIONS`, `CTF_ORGANIZER_PERMISSIONS`, `shared.api_tokens.scopes` | Participant submission history uses `ctf:play:read`; any organizer history API must use organizer permissions and `ctf:event:read`, not a widened participant endpoint. |
| Browser JSON parsing | `ctf.views._parsing._parse_body_object`, `_get_body_str`, `_parse_body_uuid` | Reuse existing parser helpers on legacy function views; do not add endpoint-local body parsing. |
| DRF validation and errors | `ctf.api._base.JSONBodySerializer`, `shared.api.errors.api_error_response`, `config/_drf_settings.py` | Canonical `/api/v1/ctf/` errors use the shared `{"error": {...}}` envelope and request id when present. |
| Domain exceptions | `ctf.exceptions.CTFError` subclasses | Do not add a submission-history exception hierarchy. Map existing exceptions to bounded HTTP responses. |
| Client IP/audit source | `risk_register.services.get_client_ip` | Keep trusted IP handling for writes; do not add a second XFF parser. |
| Logging hygiene | module loggers plus `shared.log_sanitize.safe_log_value` | Log IDs, counts, filter names, and statuses only. Never log submitted flags, request bodies, cookies, CSRF tokens, API tokens, or invite tokens. |
| Event config shape | `CTFEvent`, `CTFEventForm`, `ctf.services.event._EVENT_MUTABLE_FIELDS`, `_event_detail_payload`, `event_form.html` | If a visibility knob is added, all event configuration surfaces must agree. No Django setting, env var, Terraform var, or Kubernetes setting for per-event participant history. |
| Tests | `tests/ctf/conftest.py`, `tests/ctf/factories.py`, `test_participant_views.py`, `test_api_view_flows.py`, `test_drf_api_token_access.py`, service tests | Use DB-backed Django/DRF client tests and existing fixtures. Avoid mocked queryset-chain tests for end-to-end history behavior. |
| Traceability | Ground Control `TESTS` links for CTF-1305 | Link maintained tests, not placeholder files or incidental fixture coverage. |
| Architecture gates | `.importlinter`, `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Keep CTF isolated from `engine` and `mission_control`; do not weaken local enforcement. |

## Cross-Cutting Layers

- Auth surface: browser/session participant routes pass through Django login
  and `ctf_participant_required`; organizer routes pass through login and
  `ctf_organizer_required`; canonical `/api/v1/ctf/` routes pass through
  session-or-token auth, active actor checks, endpoint scopes, and CTF role
  permissions.
- Domain authorization: after HTTP admission, participant reads must prove the
  participant row belongs to the active or route challenge's event; organizer
  reads must prove event ownership before any filter is applied.
- Payload and query validation: correctness filters should be constrained to
  correct/incorrect/all; participant and challenge filters should be validated
  UUIDs in the target event; time filters should use aware datetimes; search
  should be length-bounded and ORM-shaped.
- Config validation: participant self-view visibility, if added, belongs to the
  event model/form/API configuration path. Unknown values or missing fields
  fail closed through model/service validation, not template defaults.
- Error-envelope leakage: participant and organizer failures return authored,
  bounded messages. Do not serialize `str(exc)`, `CTFError.to_dict()`, SQL
  errors, raw filters, submitted flag values, or stack traces.
- Secret-handling surface: submitted flags are intentionally displayed only on
  authorized history surfaces. They must not appear in logs, error bodies,
  schema examples, GitHub comments, process argv, screenshots, or broad test
  snapshots.
- Template output: continue relying on Django template escaping when rendering
  `submitted_flag`. Do not mark submitted values safe or inject them into inline
  JavaScript without JSON escaping.
- OS/runtime exposure: this work should remain in Django/Python and the
  database. It should not add environment bindings, shell commands, temp files,
  background workers, process arguments, Terraform, or Kubernetes changes.
- Import-boundary surface: CTF may use `shared`, `management.services`, and
  approved bridge/service seams. It must not import `mission_control` or
  `engine` to build submission history.

## Extensibility Seam

The durable seam is a submission-history read policy and query shape owned by
the CTF domain:

- actor: organizer or participant
- event: required organizer scope, or participant active/challenge event
- visibility: event-owned participant-history policy
- filters: correctness, participant, challenge, submitted time, bounded search
- pagination: page and page size

Keep that seam service/query-level so a future CSV export, organizer API,
per-team filter, bracket filter, or redacted participant view can reuse the same
scope and validation rules. Do not scatter filter logic across Django admin,
organizer templates, participant templates, DRF wrappers, and JavaScript.

## Gotchas And Anti-Patterns

- Do not treat `CTFSubmissionAdmin` as proof that organizer event history is
  complete; Django admin staff access and organizer event ownership are
  different authorization models.
- Do not widen participant `/api/submissions/` or `/api/v1/ctf/submissions/`
  into an event-wide organizer endpoint.
- Do not resolve a participant with an unscoped first-row lookup in
  challenge-specific history.
- Do not expose another participant's submitted flags through active-event
  confusion, cross-event challenge IDs, API-token scope confusion, or template
  context reuse.
- Do not duplicate submitted-flag storage into analytics tables, scoreboard
  rows, logs, comments, or denormalized JSON blobs.
- Do not conflate submission history with scoring totals. Incorrect attempts
  are history; only correct submissions with `points_awarded` contribute to
  score.
- Do not conflate participant self-view visibility with scoreboard visibility
  or rating visibility. If product decides one controls another, encode that as
  an explicit policy decision, not an incidental template branch.
- Do not mark submitted values as HTML-safe or include them in OpenAPI examples.
- Do not return unbounded querysets to templates or JSON responses for large
  events.
- Do not add raw SQL, local repositories, local DTO layers, or local exception
  hierarchies when ORM query helpers, CTF exceptions, and shared API envelopes
  already cover the need.

## Non-Goals

- Implementing CTF-1305 or adding tests in this preflight.
- Redesigning flag validation, attempt limits, cooldowns, scoring,
  leaderboard materialization, hint penalties, CTFd sync, or event lifecycle.
- Adding a new public API posture. Submission history is authenticated and
  role/object scoped.
- Adding background jobs, exports, analytics warehouses, retention policy,
  deletion workflows, or audit-log replacements.
- Adding new infrastructure, environment variables, Terraform variables,
  Kubernetes settings, or ADR exceptions.
