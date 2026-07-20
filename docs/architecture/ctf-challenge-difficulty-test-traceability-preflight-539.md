# CTF Challenge Difficulty Test Traceability Preflight (#539 / CTF-103)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-103` - Challenge Difficulty Levels

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. `CTF-103` already has
implementation trace links for the difficulty enum, challenge model field,
organizer create/edit form, organizer listings/details, and participant
listings/details. The upcoming work should add meaningful automated coverage and
Ground Control `TESTS` traceability for those existing contracts. It should not
redesign challenge metadata.

## Scope Boundary

`CTF-103` is the predefined, human-facing challenge difficulty scale. The
canonical value set is `ctf.enums.ChallengeDifficulty`: `easy`, `medium`,
`hard`, and `expert`.

Difficulty is:

- challenge metadata, not scoring policy;
- independent from category, tags, topics, prerequisites, visibility, and
  release scheduling;
- displayed to organizers and participants;
- mutable only through the existing challenge write contract while the event is
  content-modifiable.

The requirement does not require dynamic difficulty, participant-specific
difficulty, per-event custom scales, CTFd sync changes, scoreboard weighting, or
new analytics.

## Architecture Decisions And Guardrails

- Reuse `ctf.enums.ChallengeDifficulty` and `ChallengeDifficulty.choices()` as
  the only difficulty value/label contract. Do not create parallel literals,
  serializers, JSON schemas, constants, or template-only value maps.
- Keep persistence on `CTFChallenge.difficulty`, a Django `CharField` with
  choices and default `ChallengeDifficulty.MEDIUM.value`. Do not add another
  difficulty column, join table, migration, or event-level configuration unless
  a future requirement changes the scale model.
- Keep writes behind the existing service boundary:
  `CTFChallengeForm.to_service_data()` to
  `ctf.services.challenge.create_challenge` / `update_challenge`, or the JSON
  API handlers that call those services. `CTFChallengeForm.save()` must remain
  blocked.
- Preserve `_CHALLENGE_MUTABLE_FIELDS` as the service allowlist for organizer
  editable challenge metadata. If difficulty validation needs tightening, build
  on model choices / form choices / service error mapping rather than a second
  enum parser.
- Participant reads must continue through `participant_challenges`,
  `challenge_detail`, `get_available_challenges`, and
  `assert_challenge_readable_for_participant`. Difficulty display must not
  weaken hidden, unreleased, locked, prerequisite, active-participant, or
  same-event checks.
- Organizer reads must continue through `list_challenges_for_event`,
  `get_challenge`, and event ownership checks. A token scope or organizer role
  is not a substitute for object ownership.
- API reads should use the existing CTF JSON/DRF surfaces. The list/detail
  payloads already expose `difficulty`; create/update response shape changes
  should be deliberate and tested, not incidental.
- Ground Control `TESTS` links must point at maintained tests that assert
  difficulty behavior, not at this note, factories, broad smoke tests, audit
  files, or implementation files.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-103 coverage |
| --- | --- | --- |
| Difficulty scale | `ctf.enums.ChallengeDifficulty` | Use enum values and `choices()` in tests and fixtures; avoid duplicated string sets. |
| Model validation | `CTFChallenge.difficulty`, `CTFBaseModel.save()` / `full_clean()` | Invalid values should fail through Django choices and map to controlled API/form errors where surfaced. |
| Organizer form/DTO | `CTFChallengeForm`, `to_service_data()`, disabled `save()` | Test form validation and service DTO shape; do not persist from the form. |
| Challenge write service | `create_challenge`, `update_challenge`, `_CHALLENGE_MUTABLE_FIELDS` | Verify difficulty survives service-backed create/update with actor and event-state checks intact. |
| Organizer HTML | `admin_challenge_list`, `admin_challenge_detail`, `challenge_form.html` | Assert organizer-visible labels without bypassing ownership or modifiable-event policy. |
| Participant HTML | `participant_challenges`, `challenge_detail`, participant templates | Assert participant-visible labels only through participant-scoped, available challenges. |
| JSON / DRF API | `ctf.views.api.challenges`, `ctf.api._base`, `ctf.api.views` | Reuse JSON object validation, token/session auth, scope checks, and shared error envelopes. |
| Test helpers | `tests/ctf/conftest.py`, `tests/ctf/factories.py`, `_api_flow_helpers.py`, `rest_framework.test.APIClient` | Extend existing CTF test style; avoid large inline mocks and duplicate setup builders. |
| Import boundaries | `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR-001 | CTF may use `shared`, `cms.services`, and `management.services`; it must not import `engine` or `mission_control`. |
| Logging and errors | module loggers, `shared.log_sanitize.safe_log_value`, `ctf.views._access._json_error`, `shared.api.errors` | Do not expose raw exceptions, flag values, request bodies, SQL, or stack traces. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: organizer HTML uses `@login_required`,
  `@ctf_organizer_required`, event ownership, and service-level
  `assert_actor_owns_event`; participant HTML uses `@login_required`,
  `@ctf_participant_required`, active participant resolution, and
  challenge-scoped participant lookup; canonical API routes use
  `IsAuthenticatedSessionOrApiToken`, active actor checks, and CTF scope
  admission.
- Request shape and validation: HTML writes pass through `CTFChallengeForm`;
  legacy JSON writes pass through `_parse_body_object`; canonical DRF routes
  pass through `JSONBodySerializer`; model saves pass through `full_clean()` and
  field choices. Invalid difficulty must be a controlled validation outcome,
  not a 500 or a silently accepted string.
- Domain policy: challenge create/update still requires an organizer-owned,
  content-modifiable event. Participant display still requires a participant in
  the challenge's event plus hidden/release/prerequisite read gates.
- Error-envelope leakage: CTF legacy API errors stay bounded
  `{"error": "..."}` responses; canonical `/api/v1/ctf/` errors stay in the
  shared `{"error": {...}}` envelope. Do not return `str(exc)` from Django
  validation, service validation, or ownership failures.
- Secret-handling surface: difficulty is non-secret, but the same requests can
  carry flags, flag hashes, challenge solutions, cookies, CSRF tokens, bearer
  tokens, invite tokens, validator config, and uploaded-file metadata. Tests,
  logs, screenshots, issue comments, and traceability notes must not expose
  real values.
- Config and env shape: no new env var, Terraform variable, Kubernetes setting,
  or runtime process flag is expected. If a future scale customization requires
  configuration, it belongs in an explicit domain model and validation path, not
  process environment.
- OS/runtime exposure: this feature should remain in Django/Python and the
  database. It must not shell out, pass challenge content in argv, write temp
  files, or rely on process-local memory.
- Whole-repo gates: `.ground-control.yaml`, `.gc/plan-rules.md`, ADR-001,
  `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, and
  `scripts/adr_guard/adr_guard.py` remain in scope for validation and
  traceability work.

## Extensibility Seam

The seam is the difficulty value/label contract, not a new difficulty service.
Future additions such as a fifth level, custom labels, or localization should be
absorbed by `ChallengeDifficulty` / `choices()` plus one display helper or
template include if the repeated badge branches become change-prone. Tests
should be parameterized over enum members where practical so a future scale
change updates the canonical artifact first and then exposes every surface that
needs display changes.

Do not make difficulty drive score values. If a future requirement introduces
default points by difficulty, put that behind an explicit scoring or form default
policy while keeping stored `points` authoritative for scoring.

## Gotchas And Anti-Patterns

- Existing tests use difficulty fixture values frequently, but many do not assert
  CTF-103 behavior. Trace links should attach to tests that actually prove the
  scale, persistence, and organizer/participant display contract.
- `CTFChallenge.objects.create(...)` calls model validation through
  `CTFBaseModel.save()`, but API handlers must still map validation failures to
  controlled client errors. Do not let an invalid enum value become a 500.
- Templates currently repeat badge branches for each difficulty. Do not add more
  branch copies casually; extract a small display helper/include if a behavior
  change forces touching multiple surfaces.
- Do not conflate difficulty with category, tags, topics, bracket, solve count,
  rating, score value, prerequisites, or visibility.
- Do not satisfy the requirement by asserting only database storage. The
  statement explicitly requires display alongside challenge listings.
- Do not use CSS class presence alone as the proof of participant-visible
  behavior; assert the label or API value the user/client receives.
- Do not add CTFd-specific fields or sync behavior for this requirement.

## Non-Goals

- No implementation in this preflight note.
- No challenge metadata redesign, new serializer hierarchy, repository layer,
  exception class, validation framework, ADR, migration, or configuration knob.
- No changes to scoring, challenge release, hints, flags, attachments,
  prerequisites, ratings, scoreboard materialization, participant registration,
  CTFd sync, CMS/range integration, or platform deployment topology.
- No Ground Control `IMPLEMENTS` trace changes are required for this preflight;
  the upcoming work should add or reconcile `TESTS` links for maintained tests.
