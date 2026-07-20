# CTF Hint Penalty Scoring Preflight - Issue 519 / CTF-002

Issue 519 / `CTF-002` is a native Django CTF scoring fix that also intersects
the hint-access requirements `CTF-203` and `CTF-206`. This note records the
architecture boundary for the future implementation. It is intentionally not an
implementation plan.

## Boundary

The fix belongs in the existing hint-unlock and solve-scoring contract:

- `ctf.models.CTFHint` and `ctf.models.CTFHintUsage`
- `ctf.services.hint.use_hint`
- `ctf.services.hint.get_total_hint_penalty`
- `ctf.services.submission.submit_flag`
- `ctf.models.CTFChallenge.calculate_points_with_penalty`
- `ctf.services.scoring.calculate_score`, `get_scoreboard`, and
  `get_team_scoreboard`

The current branch already has a durable hint usage ledger. Do not redesign it
because the migrated issue body says hint usage is not persisted. The remaining
contract gap is the zero-point floor: a 100 percent cumulative hint penalty must
allow a correct solve to award `0`, and hint usage without a solve must remain
score-neutral.

For `CTF-206`, the deterministic score contract is still the same aggregate:
stored correct-solve points plus organizer awards/deductions. The broader
dynamic-scoring clause does not yet have a canonical persisted adjustment event
or scoring mode in this repo, so it should not be invented inside the hint
penalty fix.

## Architectural Decisions

- `CTFHintUsage` is the canonical durable record for participant hint unlocks.
  Do not revive legacy `CTFSubmission.hint_used` semantics or create a second
  participant-hint ledger.
- `get_total_hint_penalty(participant_id, challenge_id)` is the canonical
  penalty reader. Scoring must not recalculate hint usage from submissions,
  templates, request state, or duplicated query logic.
- Hint penalties apply only when `submit_flag` creates a correct
  `CTFSubmission`. Unlocking a hint must not create an award, deduction,
  negative submission, or participant-total mutation.
- The point floor belongs in `CTFChallenge.calculate_points_with_penalty`.
  Callers should consume the same calculation for final scoring and projected
  "points after next hint" UI values.
- Total scores and scoreboards remain aggregates over correct submissions'
  `points_awarded` plus awards. They must not subtract hint penalties again.
- Scoreboard freeze currently relies on timestamp filters over persisted solves
  and awards. Any later dynamic recalculation contract must preserve
  deterministic frozen-score behavior for the same event inputs.

## Cross-Cutting Concerns To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Participant auth surface | `@login_required`, `@ctf_participant_required`, `_get_participant_for_challenge` in `ctf.views` | Keep participant identity scoped to the route challenge's event. |
| Request parsing | `_parse_body_object`, `_parse_body_uuid`, `_get_body_str` in `ctf.views` | Do not add endpoint-specific JSON parsing or UUID conversion. |
| Domain availability | `ctf.services.challenge.assert_challenge_available_for_participant` | Hint unlock and flag submission must keep sharing event, window, release, visibility, and prerequisite gates. |
| Hint persistence | `CTFHintUsage` with `unique_active_hint_usage` | Preserve idempotent, race-safe unlocks. |
| Penalty calculation | `get_total_hint_penalty` and `CTFChallenge.calculate_points_with_penalty` | Keep cumulative penalty capping and point flooring centralized. |
| Score aggregation | `calculate_score`, `CTFParticipant.total_score`, `CTFTeam.total_score`, `get_scoreboard`, `get_team_scoreboard` | Aggregate stored solve points; do not recompute penalties in aggregate queries. |
| Exceptions | `CTFNotFoundError`, `CTFValidationError`, `CTFStateError`, `CTFRateLimitError` | Do not add a new scoring or hint exception hierarchy. |
| Logging | module-level CTF service loggers | Log IDs and point counts only; never log submitted flags or hint text. |
| Tests | `tests/ctf/test_services/test_hint.py`, `test_services/test_submission.py`, `test_models.py`, `test_scoring.py` | Cover first-solve-after-hint, unsolved-hint, 100 percent floor, UI projection, and aggregate scoreboard paths. |
| Architecture gates | `.importlinter`, `.ground-control.yaml`, `.gc/plan-rules.md`, `scripts/adr_guard/adr_guard.py` | Keep CTF isolated from `engine` and `mission_control`; run ADR guard for architecture/doc changes. |

## Security Layers

- Authn/authz: participant POSTs still enter through Django auth decorators and
  participant resolution scoped to the route challenge. The service remains safe
  for internal callers through `assert_challenge_available_for_participant`.
- Domain policy: participant/challenge event match, ACTIVE event status,
  competition window, challenge visibility, release time, prerequisites, attempt
  limits, and cooldown remain service gates before solve persistence.
- Persistence integrity: hint unlocks stay in `CTFHintUsage`; solves stay in
  `CTFSubmission`; awards stay in `CTFAward`. Do not mix these ledgers.
- Config/model validation: hint penalties keep the existing `0..100` model
  validator, and cumulative penalty capping stays in the penalty reader or point
  calculator. This fix should not add env vars, settings, migrations, or
  duplicate schemas unless a test proves a model contract is missing.
- Secret handling: submitted flags, hint text, challenge solutions, and raw
  request bodies must not appear in logs, exception details, test snapshots, or
  process arguments.
- OS/runtime exposure: the change should remain in Django/Python code and tests.
  It must not shell out, create token-bearing commands, write temp files, or add
  host-level configuration.
- Error envelope: participant-facing JSON keeps the existing `{"error": ...}`
  and solve response shapes. Do not expose hint contents or cross-event details
  in failure responses.

## Extensibility Seam

The immediate seam is the challenge-level point calculation:
`calculate_points_with_penalty(total_hint_penalty)`. The next likely variation is
an event or challenge policy such as dynamic challenge values, fixed point
costs, per-hint absolute costs, or "hints stop reducing score after solve."
That policy should be represented as an explicit parameter or model field
consumed by this calculator and the projection UI, not by re-editing
scoreboards, views, or submission aggregation.

If dynamic challenge values become in scope, the broader seam belongs in one
`ctf.services.scoring` recalculation contract parameterized by event,
challenge, and participant scope. It should not be hidden in hint unlocks,
submission views, admin annotations, or template code.

Whole-repo surfaces in scope for the future implementation:

- `shifter/shifter_platform/ctf/models.py`
- `shifter/shifter_platform/ctf/services/hint.py`
- `shifter/shifter_platform/ctf/services/submission.py`
- `shifter/shifter_platform/ctf/services/scoring.py`
- `shifter/shifter_platform/ctf/views.py`
- `shifter/shifter_platform/ctf/admin.py`
- `shifter/shifter_platform/templates/ctf/participant/challenge_detail.html`
- `shifter/shifter_platform/templates/ctf/admin/participant_detail.html`
- `shifter/shifter_platform/templates/ctf/includes/scoreboard_table.html`
- `shifter/shifter_platform/templates/ctf/includes/admin_scoreboard_rows.html`
- `shifter/shifter_platform/static/js/score-timeline.js`
- `shifter/shifter_platform/tests/ctf/test_models.py`
- `shifter/shifter_platform/tests/ctf/test_services/test_hint.py`
- `shifter/shifter_platform/tests/ctf/test_services/test_submission.py`
- `shifter/shifter_platform/tests/ctf/test_scoring.py`
- `shifter/shifter_platform/tests/ctf/test_participant_views.py`
- `docs/design/ctf-hint-access-preflight-769.md`
- `docs/audit/2026-03-23-ctf-audit/03-domain-model-scoring-participants.md`
- `.importlinter`, `.ground-control.yaml`, `.gc/plan-rules.md`,
  `scripts/adr_guard/adr_guard.py`

## Gotchas And Anti-Patterns

- Do not subtract penalties from participant total score, awards, scoreboards,
  or team totals after the solve; store the net value on the correct
  submission.
- Do not apply any penalty for a participant who unlocks a hint but never solves
  the challenge.
- Do not preserve the historical `max(1, ...)` floor in tests, templates, or UI
  projection copy after the calculator moves to a zero floor.
- Do not restore or backfill a `CTFSubmission.hint_used` concept. The
  participant detail template's current `submission.hint_used` reference is
  stale display logic, not a domain model to revive.
- Do not create negative solve values. The requirement allows `0`, not a
  participant-total deduction.
- Do not make hint unlocks submissions or use incorrect submissions to remember
  hint usage.
- Do not duplicate penalty math in `views.py`, templates, JavaScript, or
  scoreboard queries.
- Do not weaken the hint access preflight guardrails from issue 769 while
  changing scoring.
- Do not conflate CTFd's hint-cost model with the native Django CTF app's
  `CTFHintUsage` / `points_awarded` model.

## Non-Goals

- Implementing the issue in this preflight.
- Redesigning progressive hints, hint ordering, hint purchase UX, event awards,
  flag verification, scoreboards, brackets, or team scoring.
- Adding a new scoring engine, repository layer, serializer layer, exception
  hierarchy, migration, setting, or background workflow.
- Changing the standalone Polaris CTFd sync scripts or live CTFd behavior.
- Mutating historical submissions or retroactively recalculating event scores
  unless a separate migration/backfill requirement explicitly owns that policy.
