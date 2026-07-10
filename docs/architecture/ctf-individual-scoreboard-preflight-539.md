# CTF Individual Scoreboard Preflight (#521 / #539 / CTF-401)

Status: pre-implementation guidance

Date: 2026-07-01

Requirement: CTF-401, "Individual Scoreboard"

Primary repair issue: <https://github.com/Brad-Edwards/shifter/issues/521>

Test-traceability issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note narrows the CTF-401 repair and test-traceability work to the existing
native CTF architecture. It is intentionally not an implementation plan.

## Scope Boundary

CTF-401 is about the participant-facing individual scoreboard:

- rank, participant display name, total score, number of solved challenges, and
  time of last solve;
- near-real-time refresh within 30 seconds of a scoring event;
- row click-through to that participant's solve history.

The authoritative scoring and near-real-time mechanics already live in the CTF
service layer. Work for this requirement should close any participant UI/API
contract gaps and add meaningful automated coverage plus Ground Control `TESTS`
traceability. It should not redesign scoring, team leaderboards, brackets,
event lifecycle, flag submission, or platform API authentication.

## Architecture Decisions

- Treat `ctf.services.scoring.get_scoreboard` as the scoreboard payload
  contract for individual rows. The row fields are `rank`, `participant_id`,
  `name`, `team_name`, `bracket_name`, `score`, `solve_count`, and
  `last_solve`. Views, JSON responses, templates, and JavaScript must consume
  that contract instead of introducing a second row schema such as `solves`,
  `displayName`, or name-derived identities.
- Keep the existing response key `rankings` as the canonical scoreboard list
  unless a deliberate compatibility bridge is added for both legacy and
  `/api/v1` routes. A temporary `scoreboard` alias may be acceptable only as a
  compatibility bridge, not as a second row contract. Do not update only the
  server-rendered table, only the legacy `/ctf/api/...` route, or only the
  platform `/api/v1/ctf/...` route.
- The 30-second freshness requirement is satisfied by the current shape only if
  correct submissions and awards maintain the materialized leaderboard columns
  through `ctf.services.scoring._maintenance` and the participant page polls at
  an interval of 30 seconds or less. Do not move recomputation into template
  JavaScript, per-request aggregate SQL, `CTFScheduledTask`, or process-local
  cache.
- Row click-through solve history is not the same concept as the existing score
  timeline, participant self-submission API, or organizer participant detail.
  Solve history should be a safe, event-scoped projection of correct solves for
  the clicked participant. It must not expose raw submitted flags, wrong
  attempts, IP addresses, invite tokens, attempt-limit internals, or
  organizer-only submission history.
- Do not conflate individual and team scoreboards. CTF-401 is individual-mode
  behavior. Team rows do not carry `participant_id`, so team-mode behavior must
  remain separate unless a team-history requirement explicitly defines it.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-401 |
| --- | --- | --- |
| Scoreboard reads | `ctf.services.scoring.get_scoreboard`, `get_team_scoreboard`, `get_participant_rank` | Keep ranking, tie-break, freeze, bracket, and materialized-read semantics in the service layer. |
| Derived leaderboard state | `ctf.services.scoring.recompute_participant_score`, `recompute_team_score`, `recompute_event_leaderboard` | Maintain cached score, solve count, and last solve from authoritative rows. Do not add a parallel leaderboard table or cache without the #850 rebuild/invalidation contract. |
| Solve/submission reads | `ctf.services.submission.get_participant_submissions`, `ctf.services.scoring.get_score_timeline` | Use the existing query helpers, but keep "public solve history" distinct from score timeline and organizer submission history. |
| Participant eligibility | `ctf.services.participant.eligible_participant_q`, `is_active_participant`, `get_participant_by_user(event_id=...)` | Participant access, row visibility, and scoring exclusion must continue to share one predicate so disqualified rows do not leak. |
| Participant active event | `management.services.set_active_ctf_event`, `ctf.views._access._get_active_participant` | Browser scoreboard tests and page behavior must be scoped to the active CTF event, not the first participant row. |
| Legacy JSON boundary | `ctf.views.api.scoreboard`, `ctf.views._access`, `ctf.views._parsing` | Reuse login/role decorators, `_resolve_scoreboard_access`, `_authorize_timeline_access`, and `_resolve_bracket_filter`; do not add local JSON/UUID/bracket parsers. |
| Platform API boundary | `config/api_urls.py`, `ctf.api.urls`, `ctf.api._base`, `config._drf_settings`, `shared.api.errors` | Canonical `/api/v1/ctf/` responses use shared DRF auth and error envelopes. Legacy flat errors stay legacy only. |
| Templates and client UI | `templates/ctf/participant/scoreboard.html`, `templates/ctf/includes/scoreboard_table.html`, `static/js/score-timeline.js` | Reuse the include for server-rendered rows and keep client-side refresh aligned with the same row fields. |
| Tests | `tests/ctf/test_scoring.py`, `test_api_view_flows.py`, `test_drf_api_token_access.py`, `test_organizer_access.py`, `test_participant_views.py`, `static/js/*.test.js` | Cover service contract, legacy API, platform API/public exception, auth denial, participant page rendering, and any row-click JavaScript without mocking first-party scoring. |

## Cross-Cutting Layers

- Auth and authorization: the participant HTML page must keep
  `@login_required` and `ctf_participant_required`, then resolve the current
  participant through `_get_active_participant`. The legacy scoreboard API must
  keep `_resolve_scoreboard_access`: organizer owns event, or caller is an
  active participant in that exact event. Any participant-to-participant solve
  history read must prove same-event active participant membership or organizer
  ownership before returning data.
- Public API exception: `ctf.api.views.PublicScoreboardView` is the narrow
  anonymous-read exception for visible scoreboard rows. Do not automatically
  extend anonymous access to score timelines, solve history, submissions,
  challenge files, or organizer/admin views. If the row drill-down is exposed
  through `/api/v1`, it must use the authenticated CTF role/participant
  permission posture rather than the public scoreboard view.
- Request validation: scoreboard reads are GET-only. Route UUIDs should remain
  Django path-converter UUIDs, and bracket query parsing must stay in
  `_resolve_bracket_filter`. If a solve-history endpoint adds pagination or
  filters, validate them at the HTTP boundary before service calls; keep the
  default projection unfiltered other than event id, participant id, correctness,
  and optional pagination.
- Error envelopes: legacy `/ctf/api/...` routes return the existing bounded flat
  JSON errors. Canonical `/api/v1/ctf/...` routes must flow through
  `ctf.api._base._canonical_error_response` or the shared
  `shared.api.errors.api_exception_handler`. Do not return `str(exc)` or
  `CTFError.to_dict()` directly.
- Secret-handling surface: raw submitted flags, stored flag values, invite
  tokens, session cookies, CSRF tokens, Authorization headers, participant IP
  addresses, validator config, and presigned URLs must not appear in solve
  history payloads, logs, snapshots, OpenAPI examples, or error responses.
- Logging and observability: use existing request IDs from
  `config.middleware.RequestIDMiddleware` and sanitizers from
  `shared.log_sanitize`. Log IDs or safe summaries, not full request bodies or
  participant-submitted values. No new metrics stack is needed for CTF-401.
- Config and runtime shape: no new environment binding is expected. If a future
  polling interval or history page size becomes configurable, use the
  `config.settings` `_env_int` style and update `config/_env_manifest.py`.
  Do not pass flags, tokens, signed URLs, or bearer credentials through process
  argv in examples or tests.
- Channels/cache posture: polling is sufficient for the 30-second requirement.
  If push updates are chosen later, reuse the shared Channels posture in
  `config._channels` and fail-closed Redis TLS/auth validation. Do not use
  LocMemCache or an unauthenticated scoreboard socket for event correctness.
- Import boundaries: CTF code must continue to obey `.importlinter`: no direct
  CTF imports from `mission_control` or `engine`, and cross-layer behavior goes
  through approved service/bridge seams.

## Extensibility Seam

The durable seam is a single scoreboard-row history projection parameterized by
event id, participant id, viewer role, freeze cutoff, optional pagination, and
disclosure mode. For CTF-401 the disclosure mode is public-to-event correct
solves only. A future participant self-history or organizer-history surface can
reuse the same source rows with a stricter role mode without rewriting scoring
semantics.

The polling interval is a separate UI/runtime seam. Today the page can keep a
static interval at or below 30 seconds. If it becomes configurable, define it
once and render it into the page rather than duplicating magic numbers in
templates and tests.

## Gotchas And Anti-Patterns

- Do not use participant display name as a row identity or URL parameter.
- Do not expose another participant's full submission attempts as "solve
  history"; public history is correct solves only unless a requirement says
  otherwise.
- Do not reuse organizer participant-detail data for participant row
  click-through. Organizer history and participant-visible history have
  different disclosure rules.
- Do not let a disqualified participant pass access control or appear in
  rankings through a predicate that only checks `registered_at`.
- Do not make only the auto-refresh JavaScript correct while the initial
  server-rendered table remains stale, or vice versa.
- Do not let the platform `/api/v1` public scoreboard exception widen into a
  public submission-history API.
- Do not add a new CTF exception hierarchy, DTO package, repository layer,
  websocket protocol, scheduler workflow, or cache abstraction for this
  requirement.

## Non-Goals

- No scoring redesign, alternate ranking rules, or new materialization strategy.
- No team-scoreboard or team-history requirement expansion.
- No CTFd compatibility work.
- No platform API migration beyond keeping touched CTF routes consistent with
  the existing `/api/v1/ctf/` posture.
- No new ADR; existing ADR-001, ADR-003, ADR-004, #850 scoreboard readiness, and
  #1121 CTF API preflight cover the enforceable architecture.
