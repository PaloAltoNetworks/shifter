# CTF Scoreboard Contract Preflight (#521 / CTF-406)

Status: pre-implementation guidance

Date: 2026-07-01

Requirement: `CTF-406` - Tie-Breaking Rules

Related requirement: `CTF-401` - Participant Scoreboard

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/521>

This note is intentionally not an implementation plan. The existing
tie-breaking rule is already owned by `ctf.services.scoring`; issue #521 should
repair participant scoreboard wiring and add drill-down affordances without
creating another ranking path, schema family, or access-control policy.

## Scope Boundary

The canonical scoreboard row contract is the dict returned by
`ctf.services.scoring.get_scoreboard()` and `get_team_scoreboard()`:
`rank`, `name`, `score`, `solve_count`, `last_solve`, plus the relevant
participant/team/team-name/member/bracket fields. HTML, legacy JSON, and the
public DRF scoreboard surface may adapt this for presentation, but they must not
sort, re-rank, or recompute scores.

The current maintained response key is `rankings`, with `bracket_rankings` for
filtered views. If stale consumers still expect `scoreboard` or `solves`, fix
the consumer to the canonical row contract rather than adding alias fields that
make the API ambiguous.

Participant row click-through must not point to organizer-only participant
detail pages. If participants can inspect another participant's solve history,
that surface must be explicitly participant-safe: same event, active
participant access, scoreboard visibility and freeze semantics, correct-solve
data only, and no submitted flags, incorrect attempts, IP addresses, email
addresses, invite tokens, or internal notes.

## Architecture Decisions And Guardrails

- Keep ranking and CTF-406 tie-breaking in `ctf.services.scoring`. The existing
  CTF-406 preflight covers score-descending plus earliest-last-solve ordering,
  null ordering, materialized hot reads, and recompute cold reads.
- Keep URL/link construction out of the scoring service. Scoring rows carry
  stable IDs; HTML views, JSON view adapters, or templates may add presentation
  links for the current audience.
- Use the existing row partials before adding markup copies:
  `ctf/includes/scoreboard_table.html` for participant pages and
  `ctf/includes/admin_scoreboard_rows.html` for organizer pages.
- Keep bracket handling in `ctf.views._parsing._resolve_bracket_filter()`.
  Do not introduce client-provided sorting, raw UUID parsing, or a second
  query schema for scoreboard filtering.
- Reuse existing submission/timeline read paths for drill-down:
  `ctf.services.scoring.get_score_timeline()` for score progression and
  `ctf.services.submission.get_participant_submissions()` for submission
  history. Any participant-visible projection must be a bounded, correct-solve
  projection, not the raw `CTFSubmission` model.
- Legacy `/ctf/api/...` responses keep the flat legacy shape; canonical
  `/api/v1/ctf/...` responses pass through `ctf.api._base` and shared DRF error
  handling. Do not fork response envelopes for this feature.
- A user-visible scoreboard repair should add a `changelog.d/521.fixed.md`
  fragment during implementation. This docs-only preflight does not need one.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #521 |
| --- | --- | --- |
| Ranking source | `ctf.services.scoring.get_scoreboard`, `get_team_scoreboard` | Use returned order and fields; no template, JavaScript, or serializer ranking. |
| Tie-breaking semantics | `ctf/services/scoring/_read.py`, `_nulls_last()` | Preserve earliest-last-solve wins and backend-independent null ordering. |
| Score materialization | `recompute_participant_score`, `recompute_team_score`, `CTFParticipant.last_solve_at`, `CTFTeam.last_solve_at` | Read cached live rows or existing recompute paths; no schema change for #521. |
| Participant eligibility | `ctf.services.participant.eligible_participant_q()`, `is_active_participant()` | Disqualified/unregistered rows must not appear in scoreboards or drill-down. |
| Active participant resolution | `ctf.views._access._get_active_participant()` | Participant HTML views stay scoped to `active_ctf_event_id`. |
| Scoreboard authorization | `ctf.views.api.scoreboard._resolve_scoreboard_access()`, `PublicScoreboardView` | Preserve event ownership, event membership, public visibility, and freeze behavior. |
| Timeline authorization | `_authorize_timeline_access()` | If broadened for row drill-down, do it deliberately with same-event and visibility checks. |
| Submission history | `ctf.services.submission.get_participant_submissions()` | Project safe fields only; never expose `submitted_flag` or incorrect-attempt details to other participants. |
| Request parsing | `ctf.views._parsing`, DRF serializers via `ctf.api._base` | Validate query/body shapes centrally. |
| Error envelopes | `_json_error()`, `_canonical_error_response()`, `shared.api.errors` | Controlled messages only; no raw exception strings. |
| Logging hygiene | module loggers, `shared.log_sanitize.safe_log_value()` | Log IDs and bounded messages only; no flags, tokens, cookies, or signed URLs. |
| Tests | `tests/ctf/test_scoring.py`, `test_participant_views.py`, `test_api_view_flows.py`, `test_api_error_paths.py`, `test_brackets.py`, `test_drf_api_token_access.py`, static JS tests | Extend existing suites rather than adding broad smoke tests or large mocks. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: participant HTML remains behind `@login_required`,
  `@ctf_participant_required`, and active-event participant resolution.
  Organizer HTML remains behind `@ctf_organizer_required` plus event ownership.
  Legacy scoreboard JSON remains behind `@login_required`, `ctf_role_required`,
  and `_resolve_scoreboard_access()`. The DRF public scoreboard remains the only
  anonymous CTF read exception.
- Domain policy surface: scoreboard visibility, frozen scoreboard cutoffs,
  bracket filters, team mode, and participant eligibility must apply identically
  on initial render, auto-refresh, and drill-down links.
- Request validation surface: existing path converters validate UUID route
  shapes; bracket query handling stays in `_resolve_bracket_filter()`. New
  drill-down query options, if any, need a central parser/serializer and must
  not become free-form sort/filter fields.
- Error-envelope surface: legacy CTF JSON returns controlled flat
  `{"error": "..."}` messages; `/api/v1/ctf/...` returns the shared API error
  envelope. Hidden scoreboards keep `{"scoreboard_hidden": true}`.
- Secret-handling surface: `CTFSubmission.submitted_flag`, stored flag values,
  invite tokens, API tokens, CSRF tokens, cookies, IP addresses, emails,
  presigned URLs, and raw provider data must not appear in participant-visible
  history, logs, JavaScript bootstrap JSON, test snapshots, or error payloads.
- Persistence surface: source truth remains `CTFSubmission` and `CTFAward`;
  materialized participant/team score fields remain rebuildable caches. No new
  table, migration, environment variable, scheduler, or process-local cache is
  required for #521.
- OS/runtime surface: this feature should stay inside Django views, templates,
  static JavaScript, and service reads. Do not shell out, pass secrets in argv,
  write temp files, or introduce runtime config binding.
- Import-boundary surface: `ctf` code may use `shared` helpers and existing CTF
  services. Do not import `mission_control` or `engine` directly for
  scoreboard/drill-down behavior.

## Extensibility Seams

The scoreboard row stays service-owned, while row actions are presentation-owned.
If auto-refresh needs links, add a presentation field such as a history URL in
the JSON view adapter, not in `ctf.services.scoring`.

The participant-history projection is the future-facing seam. Keep an explicit
audience or mode boundary, for example self, organizer, or participant-visible,
so a later requirement can add richer self-history or organizer filters without
exposing raw submission data to the public scoreboard path.

Team mode is a separate seam. Participant rows may link to participant history;
team rows should not fake a participant history. A future team drill-down should
have its own team-safe projection rather than overloading `participant_id`.

## Gotchas And Anti-Patterns

- Do not conflate the CTF-406 tie-breaker with row click-through. Last solve is
  the ranking tie-breaker; solve history is a display/navigation feature.
- Do not restore stale `scoreboard` or `solves` aliases when `rankings` and
  `solve_count` are the maintained contract.
- Do not link participant users to `admin_participant_detail`; that route
  exposes organizer context and uses organizer authorization.
- Do not expose incorrect attempts, submitted flags, attempt IPs, email
  addresses, invite state, or award reasons to other participants through
  row click-through.
- Do not make the score timeline broadly public as collateral for the public
  scoreboard exception.
- Do not duplicate status enums, error classes, JSON parsers, score row schemas,
  or JavaScript ranking logic.
- Do not let bracket-filtered auto-refresh update the overall table with the
  wrong result set; initial render and refresh must select the same row list.

## Non-Goals

- No implementation in this preflight note.
- No scoring redesign, configurable tie-breakers, dynamic scoring, award
  semantics change, ranking migration, or database schema change.
- No new public API posture beyond the existing public scoreboard exception.
- No new CTF exception hierarchy, validation framework, repository layer,
  environment variable, management command, scheduler, or deployment change.
- No changes to challenge solving, flag validation, range provisioning,
  notifications, participant import, team membership, or Ground Control
  `IMPLEMENTS` links.
