# CTF Event Scoring Mode Preflight - Issue 520 / CTF-201

Status: pre-implementation guidance

Requirement: `CTF-201`, "Standard Scoring"

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/520>

This note records the architecture boundary for adding explicit event-level
scoring mode configuration. Issue #520 also intersects the broader `CTF-002`
scoring-system requirement, but this preflight is scoped to the `CTF-201`
standard-mode boundary. It is intentionally not an implementation plan.

## Scope Boundary

Issue #520 is not a rewrite of CTF scoring. The repo already persists the
authoritative score ledger as correct `CTFSubmission.points_awarded` rows plus
organizer `CTFAward` rows, with live leaderboard state materialized and
rebuildable from those rows.

The missing contract is explicit event configuration and dispatch: an event must
say which scoring mode it uses, and solve scoring must call a scoring-mode
boundary even while `standard` is the only supported mode.

Standard mode means the base challenge value is fixed at
`CTFChallenge.points` and does not depend on solve count. Existing hint penalty
and award behavior are separate concerns. Do not hide hint, award, team,
bracket, freeze, or dynamic-value semantics inside the word "standard."

## Architecture Decisions

- `CTFEvent` owns the scoring mode. Add it as a first-class event field with a
  default of `standard`, not inside `range_config`, Django settings,
  environment variables, Terraform variables, Kubernetes values, or template
  state.
- The allowed mode values belong with the other CTF enums in `ctf.enums` and
  should use the existing `StrEnum` / `choices()` pattern.
- Existing events must default cleanly to `standard` through the model default
  and migration default/backfill. Historical `CTFSubmission.points_awarded`
  values remain authoritative; do not retroactively rewrite them for this
  change.
- Solve-time point calculation must dispatch through one scoring-service
  resolver or strategy entrypoint in `ctf.services.scoring`. The submission view,
  event views, templates, admin JavaScript, and scoreboard queries must not
  branch on scoring mode.
- `standard` mode's strategy returns the fixed challenge value as the base
  solve value. Any existing participant-specific modifier, such as hint penalty,
  must remain an explicit modifier input or policy step rather than a hidden
  alternate interpretation of standard scoring.
- Scoreboards, ranks, timelines, stats, and leaderboard maintenance continue to
  aggregate stored `points_awarded` plus awards. They must not recalculate
  standard challenge values from `CTFChallenge.points` or solve counts.
- Organizer-visible surfaces must expose the selected mode wherever event
  configuration is shown or edited: event form, event detail/list/API payloads,
  and Django admin. Participant scoreboards do not need a new scoring algorithm
  display for this issue.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Event config persistence | `ctf.models.CTFEvent`, Django migrations, `CTFBaseModel.save()` validation | Add one typed event field with model validation; do not create a parallel config table or JSON blob. |
| Enum/value schema | `ctf.enums` `StrEnum` classes with `choices()` | Add scoring modes once and reuse that enum in model, forms, API, and tests. |
| Event mutations | `ctf.services.event.create_event`, `update_event`, `_EVENT_MUTABLE_FIELDS` | Add the field to the existing allowlist only if organizers may set it. Do not mass-assign unreviewed request keys. |
| Organizer HTML form | `CTFEventForm` and `templates/ctf/admin/event_form.html` fetch wiring | Keep form/API/client wiring aligned with the model field and event service. |
| JSON parsing | `ctf.views._parsing._parse_body_object`, DRF `JSONBodySerializer` wrapper | Do not add endpoint-local body parsers or duplicate enum parsing. |
| API auth/scopes | `ctf.api._base`, `CTF_ORGANIZER_PERMISSIONS`, `shared.api_tokens.scopes.CTF_EVENT_*` | Event scoring mode is event configuration, so existing event read/write scopes apply. |
| Organizer ownership | `_resolve_owned_event_json`, `_check_event_ownership`, `ctf.services.authorization.assert_actor_owns_event` | Scopes and organizer role do not authorize another organizer's event. |
| Solve workflow | `ctf.services.submission.submit_flag` | Keep challenge availability, flag verification, duplicate-solve rejection, attempt limits, cooldowns, transaction locking, and leaderboard maintenance in the service path. |
| Scoring service boundary | `ctf.services.scoring` package and public re-export seam | Put mode dispatch in the scoring package and preserve existing import/test seams. |
| Hint modifier | `ctf.services.hint.get_total_hint_penalty`, `CTFChallenge.calculate_points_with_penalty` | Do not duplicate hint math in a scoring-mode enum, view, template, or scoreboard query. |
| Score aggregates | `calculate_score`, `get_scoreboard`, `get_team_scoreboard`, `get_participant_rank`, `_maintenance.recompute_*` | Continue reading/writing stored awarded points and awards as the score ledger. |
| Error handling | `CTFError` subclasses, `_json_error`, DRF `_canonical_error_response` | Do not add a scoring-mode exception hierarchy or return raw validation exception text. |
| Logging | module loggers plus `shared.log_sanitize.safe_log_value` | Log event IDs, mode values, and point totals only; never flags, tokens, request bodies, or validator secrets. |
| Tests | CTF model, event API, submission, scoring, and view-flow tests | Cover default/backward compatibility, organizer visibility, invalid mode rejection, strategy dispatch, and unchanged standard scoring. |
| Architecture gates | `.importlinter`, `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Keep CTF within approved import boundaries and run ADR guard for architecture-impact changes. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: organizer event configuration continues through Django session
  auth and `@ctf_organizer_required` on legacy views, plus
  `CTF_ORGANIZER_PERMISSIONS` and `CTF_EVENT_WRITE` on DRF-wrapped API routes.
  Participant solve paths continue through `@ctf_participant_required` and
  challenge-scoped participant resolution.
- Object policy surface: event reads/writes must still prove event ownership
  with `_resolve_owned_event_json` or the equivalent service-level owner check.
  Scoring mode must not be mutable by participants or by organizers who do not
  own the event.
- Request validation surface: JSON bodies still pass `_parse_body_object` on
  legacy routes and `JSONBodySerializer` on `/api/v1/ctf/` routes. Mode values
  must be validated by the enum/model field and surfaced as controlled 400
  errors, not as raw `ValueError`, `ValidationError`, or 500 responses.
- Config shape surface: this is event-owned persisted configuration. No new
  env binding, settings parser, config manifest entry, Terraform variable,
  Kubernetes value, scheduler flag, or process argument is expected.
- Persistence surface: model validation, migration defaults, soft-delete-aware
  managers, `CTFSubmission.points_awarded`, `CTFAward.points`, and
  materialized `cached_*` leaderboard columns remain the canonical storage
  surfaces. A mode field must not bypass rebuildability of the leaderboard.
- Transaction/concurrency surface: `submit_flag` already computes correctness,
  then serializes writes with `transaction.atomic()` and
  `CTFParticipant.objects.select_for_update()`. Standard-mode dispatch must be
  deterministic and side-effect free; future non-standard strategies must not
  add external calls or unbounded work inside the participant row lock.
- Error-envelope surface: legacy CTF JSON endpoints keep bounded flat
  `{"error": "..."}` responses; `/api/v1/ctf/` keeps the shared DRF error
  envelope through `_canonical_error_response`. Do not serialize
  `CTFError.to_dict()` or raw exception strings to clients.
- Secret-handling surface: this change should not touch secrets, but it runs
  through the solve path where submitted flags, flag hashes, validator config,
  session cookies, CSRF tokens, invite tokens, API tokens, and presigned URLs are
  sensitive. They must not appear in logs, errors, docs examples, test
  snapshots, shell commands, process argv, or GitHub comments.
- OS/runtime exposure surface: no shell-out, temp-file protocol, subprocess,
  host-level service, cache daemon, Redis/Channels dependency, or runtime
  setting should be introduced for scoring mode selection.
- Import-boundary surface: stay inside `ctf` and approved `shared` helpers.
  Do not import `mission_control`, `engine`, or CTFd/Polaris scripts to model
  native CTF scoring modes.

## Extensibility Seam

The durable seam is:

1. event-owned `scoring_mode`;
2. one scoring-service dispatch function or registry keyed by that mode; and
3. a solve-context input that can carry event, challenge, participant, and
   explicit modifier data such as total hint penalty.

The next likely variation is dynamic challenge value by solve count. That
future mode should add one enum value and one strategy implementation without
rewriting organizer views, submission API parsing, scoreboards, timelines, or
leaderboard maintenance. If a future mode requires score recomputation instead
of persisted awarded points, that policy needs its own migration/rebuild design;
it must not be smuggled into this standard-mode defaulting change.

## Gotchas And Anti-Patterns

- Do not conflate scoring mode with team mode, brackets, scoreboard visibility,
  scoreboard freeze, awards, hint penalties, challenge difficulty, attempt
  limits, or release/prerequisite gates.
- Do not treat "standard" as "whatever the old code happened to do." The mode
  must mean fixed base challenge points independent of solve count.
- Do not branch on scoring mode in templates, JavaScript, views, management
  commands, or aggregate queries. Dispatch belongs in the scoring service.
- Do not recalculate historical standard scores from `CTFChallenge.points`;
  challenge point edits and historical submissions are separate policy
  questions, and stored `points_awarded` is the current ledger.
- Do not add a generic plugin engine, repository layer, serializer layer,
  exception tree, cache, queue, or background worker for a single `standard`
  strategy.
- Do not store scoring mode in `range_config`; range provisioning config and
  scoring semantics are different concepts.
- Do not weaken CSRF, token scope checks, event ownership, participant
  eligibility, challenge availability, or error sanitization while adding the
  configuration field.

## Non-Goals

- Implementing issue #520 in this preflight.
- Implementing dynamic scoring, decay formulas, CTFd sync behavior, hint-policy
  redesign, award redesign, team-scoring redesign, or scoreboard materialization
  changes.
- Replacing existing CTF services, model packages, view helpers, DRF wrapper
  posture, or error-envelope conventions.
- Adding new environment/runtime configuration, infrastructure, background
  workflows, import-boundary exceptions, or ADR exceptions.
- Backfilling or mutating historical submission scores beyond defaulting the new
  event configuration for existing events.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups that touch `shifter/shifter_platform` should also run
the focused CTF model, service, API, and view tests for the changed surfaces.
