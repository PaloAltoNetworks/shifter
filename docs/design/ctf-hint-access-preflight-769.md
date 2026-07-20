# CTF Hint Access Preflight - Issue 769

## Scope

Issue 769 / GitHub #519 is a participant-facing security and scoring fix for
the CTF hint unlock path and CTF-002 scoring correctness. The implementation
must keep hint authorization, release-state checks, durable hint usage, and
score calculation as one domain contract.

This is not a new hint system. Current code already has progressive hints and a
durable usage ledger:

- `ctf.services.hint.use_hint`
- `ctf.models.CTFHint`
- `ctf.models.CTFHintUsage`
- `ctf.services.hint.get_total_hint_penalty`
- `ctf.services.submission.submit_flag`

## Architectural Decisions

- The canonical durable record for hint usage is `CTFHintUsage`. Do not revive
  legacy `CTFSubmission.hint_used` semantics or add another participant-hint
  ledger.
- The canonical penalty reader is `get_total_hint_penalty(participant_id,
  challenge_id)`. Scoring must continue to consume cumulative unlocked hint
  penalties through `submit_flag`.
- Hint penalties reduce solve awards to a floor of `0`, not `1`. A 100 percent
  cumulative hint penalty on a correct solve must persist `points_awarded=0`
  and the normal scoreboard/timeline aggregations must derive from that stored
  value.
- The current supported scoring mode is static challenge points plus awards and
  hint penalties. Do not introduce dynamic scoring, score recalculation jobs, or
  a second scoring-mode schema while fixing this issue.
- Hint unlock authorization belongs in the CTF hint service, not only in the
  Django view. Views may shape HTTP input and responses, but the service must be
  safe against direct/internal callers.
- Participant hint access must use the same availability policy shape as flag
  submission: participant/challenge event match, active event, competition time
  window, non-hidden/non-locked challenge, released challenge, and prerequisite
  gating when challenge availability requires it.
- The route challenge id and optional body hint id must describe the same
  challenge. A request to `/ctf/api/challenges/<challenge_id>/hint/` must not be
  able to unlock a hint for a different challenge in the same event.

## Cross-Cutting Concerns To Reuse

- Auth surface: `@login_required`, `@ctf_participant_required`, and
  `get_participant_by_user` in `ctf.views`.
- Domain exceptions: `CTFNotFoundError`, `CTFValidationError`, and
  `CTFStateError` from `ctf.exceptions`; do not add a parallel exception
  hierarchy.
- Event and challenge state: `EventStatus.ACTIVE`, `CTFChallenge.is_released`,
  challenge `visibility`, event `event_start`/`event_end`, and
  `check_prerequisites_met`.
- Persistence: `CTFHintUsage` with `unique_active_hint_usage`; preserve
  idempotent unlock behavior.
- Scoring: `CTFChallenge.calculate_points_with_penalty` and
  `get_total_hint_penalty`; keep the penalty calculation in one place.
- Score aggregation: `ctf.services.scoring.calculate_score`,
  `get_scoreboard`, `get_team_scoreboard`, `get_score_timeline`, and
  participant/team `total_score` properties already derive scores from
  persisted `CTFSubmission.points_awarded` and `CTFAward.points`.
- Observability: module-level `logger` in CTF services with IDs only. Do not log
  hint text, submitted flags, or other challenge secrets.
- API responses: existing CTF view `JsonResponse({"error": str(e)}, status=...)`
  conventions and 404/400 split for not-found versus validation/state errors.
- Architecture gates: `.importlinter`, `scripts/adr_guard/adr_guard.py`, and
  `.ground-control.yaml` lint command remain in scope for validation.

## Security Layers

- Authn/authz: the endpoint remains participant-only through Django decorators,
  then resolves the current participant from the authenticated user.
- Domain authorization: the service must reject cross-event participant/hint
  access and challenge-id/hint-id mismatches.
- Availability policy: the service must reject inactive events, out-of-window
  active events, hidden or locked challenges, unreleased challenges, and unmet
  prerequisites before returning hint text.
- Persistence integrity: unlock creation must be idempotent and race-safe against
  repeated requests for the same participant and hint.
- Error envelope: responses must not disclose hint text or cross-event challenge
  details on failure. Details in exceptions should be useful for logs/tests
  without becoming a hint enumeration surface in participant responses.
- Secret handling and OS exposure: this change should not introduce environment
  variables, shell commands, process arguments, or config-bound secrets.

## Extensibility Seam

Keep challenge availability checks factored as a reusable CTF-domain helper or
private service function rather than duplicating the `submit_flag` policy block.
The next likely variation is reusing the same participant challenge-availability
policy for attachments, connection info, per-hint release times, or organizer
preview bypasses. If a bypass is needed later, make it an explicit parameter at
that policy seam, not an implicit view-side branch.

If a future requirement adds dynamic scoring or multiple event-level scoring
modes, the seam belongs behind one canonical score-award calculator used by
`submit_flag`; mode selection should be an event-owned setting with an enum and
model/form/API validation. Scoreboard, timeline, participant, and team totals
should keep reading persisted awarded points until a deliberate recalculation
contract is designed.

## Non-Goals And Anti-Patterns

- Do not design a new scoring model, hint purchase currency, or admin workflow.
- Do not make hint unlocks submissions.
- Do not make scoreboards recompute hint penalties from live hint rows after the
  solve; the solve record's `points_awarded` is the immutable competition
  result unless a separate audited recomputation feature is designed.
- Do not bypass the CTF service layer from views to write `CTFHintUsage`
  directly.
- Do not add duplicate serializers, DTOs, validators, or exception classes for
  this endpoint.
- Do not weaken challenge visibility, release, prerequisite, or event time-window
  checks to make hints easier to unlock than flags.
- Do not log hint contents, flags, or raw request bodies.
