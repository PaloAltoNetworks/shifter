# Native CTF Scoreboard Readiness Preflight (#850)

Status: pre-implementation guidance

Date: 2026-06-21

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/850>

## Scope Boundary

Issue #850 is a native-Django CTF readiness risk. It is not a diagnosis of the
past CTFd-backed live events and must not merge native CTF and CTFd evidence
into one "CTF scoring" bucket.

The shipping work should first measure the native CTF request paths under
realistic event load, then decide whether the measured bottleneck requires a
design change. The decision may be "no app-side design change yet" if the
evidence supports that. Do not add cached/materialized leaderboard state,
background recomputation, push updates, or new metrics infrastructure just
because those are plausible fixes.

The measured native paths are:

- flag submission through `ctf.views.api_submit_flag` and
  `ctf.services.submission.submit_flag`;
- participant dashboard through `ctf.views.participant_dashboard`;
- participant/admin scoreboard through `ctf.views.scoreboard`,
  `ctf.views.admin_scoreboard`, and `ctf.views.api_scoreboard`;
- timeline through `ctf.views.api_score_timeline` and
  `ctf.services.scoring.get_score_timeline`.

The required evidence is per-route query count, DB time, portal app CPU, and
p95/p99 response latency. Scoreboard polling and submission writes must be
reported separately so read pressure, write pressure, and bcrypt/PBKDF2 CPU
are not conflated.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #850 |
| --- | --- | --- |
| Event load harness | `docs/architecture/event-load-harness-preflight-926.md` | Reuse the profile, actor-source, route-catalog, metrics-adapter, and sanitized report envelope. Do not create a second load-test architecture for native CTF. |
| Native scoring contract | `ctf.services.scoring.calculate_score`, `get_scoreboard`, `get_team_scoreboard`, `get_participant_rank`, `get_score_timeline` | Any cache/materialized read path must preserve the existing service-level dimensions: event, individual/team mode, bracket, participant visibility, and freeze cutoff. |
| Submission contract | `ctf.services.submission.submit_flag`, `ctf.services.challenge.verify_flag`, `assert_challenge_available_for_participant` | Keep flag verification, attempt limits, cooldowns, hint penalties, duplicate-solve rejection, and audit row creation in the service layer. Do not move this logic into views or the harness. |
| Eligibility and event scoping | `ctf.services.participant.eligible_participant_q`, `is_active_participant`, `get_participant_by_user(event_id=...)`, view helpers `_get_active_participant` and `_get_participant_for_challenge` | Scoring, access control, dashboard rank, and scoreboard data must use the same eligibility predicate and event-scoped participant lookup. |
| JSON parsing and API validation | `ctf.views._parse_body_object`, `_get_body_str`, `_parse_body_uuid`, `_resolve_bracket_filter` | Do not add endpoint-local JSON parsers, duplicate UUID parsing, or bracket parsing. |
| CTF exceptions | `ctf.exceptions.CTFError` subclasses | Do not add a parallel scoring exception hierarchy. New failure modes should use authored `CTFError` subclasses or existing shared user-facing error helpers for generic exceptions. |
| Error leakage controls | `shared.errors.safe_user_message`, `classify_user_message`, and existing CTF JSON envelopes | Do not surface raw validator/network exception text, raw submitted flags, raw request bodies, SQL text, or stack traces in CTF API responses or load reports. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint` | Keep logs structured and sanitized. Never log submitted flags, cookies, invite tokens, CSRF tokens, or secret-bearing validator config. |
| Channel layer and push notifications | `config/_channels.py`, `shared.notifications`, `SharedNotificationConsumer`, `shared.channels.groups` | If push updates are chosen later, reuse the shared notification/Channels posture and its auth/topic validation. Do not add an unauthenticated scoreboard socket or bypass Redis TLS/auth fail-closed behavior. |
| Cache posture | Django cache only when configured as a shared deployed backend; `config/_channels.py` for Redis channel-layer posture | Do not assume LocMemCache is event-safe across workers. If cache is chosen, its keys and invalidation must be explicit and deployment posture must be named. |
| Scheduled background work | `CTFScheduledTask` and `run_ctf_scheduler` | This scheduler is a due-task poller for event automation, not a high-throughput per-submission queue. Do not use it for near-real-time recompute unless the measured design proves bounded task volume and acceptable staleness. |
| Persistence source of truth | `CTFSubmission`, `CTFAward`, `CTFParticipant`, `CTFTeam`, `CTFBracket`, `CTFEvent` models and migrations | Submissions and awards remain authoritative. Derived leaderboard state, if added later, must be explicitly derived, invalidated, and rebuildable. |
| Tests | `tests/ctf/test_scoring.py`, `test_scoring_timeline.py`, `test_services/test_submission.py`, `test_api_view_flows.py`, and `docs/adr/README.md` patching policy | Drive real ORM/service/view behavior. Patch real process/network/cloud boundaries only; do not patch first-party scoring functions to make performance tests pass. |

## Cross-Cutting Layers

- Auth and authorization: all browser/API measurements must pass Django
  session auth plus `@login_required`, `ctf_participant_required` or
  `ctf_role_required`, `_resolve_scoreboard_access`, `_authorize_timeline_access`,
  and event ownership/participant membership checks. Do not add test-only auth
  bypasses or admin-token participant traffic.
- Request validation: `api_submit_flag` must keep `_parse_body_object` and
  `_get_body_str` as the body shape gate. Bracket filters must continue through
  `_resolve_bracket_filter`. Malformed bodies stay 400 JSON envelopes.
- Secret-handling surface: submitted flags, invite tokens, session cookies,
  CSRF tokens, CTFd tokens, HTTP-validator headers, Redis AUTH material, DB
  credentials, and report raw logs are secret-bearing. Keep them out of argv,
  process listings, shell history, logs, reports, screenshots, artifacts, and
  GitHub comments.
- Config shape: load profiles belong in the #926 harness profile/config, not
  Django settings, Terraform variables, or Kubernetes values. If a later app
  fix introduces a cache TTL, recompute debounce, or polling interval knob, use
  the existing `config.settings` `_env_int` / `_env_bool` parsing style and
  document the deployed default.
- Redis and Channels posture: Redis-backed push or cache-adjacent work must not
  weaken `CHANNEL_LAYER_BACKEND`, `REDIS_TLS`, `REDIS_PASSWORD`, or
  `REDIS_CA_PEM` fail-closed checks in `config/_channels.py`. Do not rely on
  process-local memory for event correctness in a multi-worker deployment.
- Error envelopes: CTF API responses should expose authored status/error
  categories and bounded details such as `retry_after_seconds`. Load reports
  aggregate errors by route, status, and CTF error code; they must not copy raw
  exception strings or response bodies.
- Observability: use existing ECS app logs, provider metrics, Django query
  capture in tests/harness code, and the #926 report envelope. Do not introduce
  Prometheus, statsd, public diagnostics, or a durable telemetry schema for this
  issue.
- OS/runtime exposure: bcrypt/PBKDF2 verification consumes portal CPU by
  design. The measurement must record portal process CPU, worker/process count,
  DB connection posture, client CPU/socket limits, and whether the load client
  became the bottleneck.
- Persistence and transaction boundaries: any derived leaderboard state must be
  updated after authoritative submission/award/team/participant changes are
  committed. It must have a rebuild path and must preserve freeze semantics.

## Extensibility Seam

The durable parameter seam is the native CTF load profile plus the scoreboard
read dimensions.

The profile must carry participant count, challenge count, team mode, bracket
count, flag-verifier mix (`bcrypt`, `pbkdf2`, regex, HTTP/programmable when in
scope), submission correctness mix, dashboard/timeline frequency, scoreboard
poll interval, ramp, duration, target environment, and metrics adapter.

The scoreboard read dimensions are event id, board type (individual or team),
optional bracket id, optional freeze cutoff, viewer role (participant or
organizer), and optional limit. If materialization or caching is accepted
later, those dimensions belong in the cache key or materialized-row identity.
Changing from 200 to 500 participants, adding brackets, freezing the board, or
switching polling to push should be profile/config and read-contract changes,
not a rewrite of scoring semantics.

## Gotchas

- `get_participant_rank()` currently rebuilds the event scoreboard and scans it.
  Measuring submit/dashboard paths must include this cost when those paths
  return rank.
- `participant_dashboard` calls both `calculate_score()` and
  `get_participant_rank()`. Do not call dashboard latency "scoreboard only" or
  "submission only".
- `api_submit_flag` verifies the flag before creating the submission row. A
  high wrong-answer rate can make CPU the bottleneck even with few correct
  submissions.
- Existing model properties such as `CTFParticipant.total_score`,
  `CTFTeam.total_score`, and `solved_challenge_count` are convenient but can
  hide extra aggregate queries. Use the service contract for event scoreboard
  reads.
- Freeze, hidden-scoreboard, organizer-visible, participant-visible, team, and
  bracket views are distinct result contracts. A cache that ignores one of
  those dimensions leaks or misranks data.
- CTFd and native CTF have different auth, persistence, API, and scoring
  models. Native evidence must not be used as a root-cause claim for CTFd
  events or issue #846.

## Anti-Patterns

- Direct aggregate SQL or ORM calls from a load harness to "simulate" scoring.
- A one-off scoreboard schema that duplicates `CTFSubmission`/`CTFAward`
  semantics without an invalidation/rebuild contract.
- Per-submission CTFScheduledTask rows for near-real-time recomputation without
  proving scheduler capacity and staleness bounds.
- Process-local LocMem cache used as event-ready leaderboard state across
  multiple portal workers or pods.
- Returning raw `str(Exception)` from new generic error paths or copying raw API
  bodies into evidence reports.
- Logging flags, tokens, HTTP-validator secrets, cookies, CSRF values, SQL, or
  full signed URLs.
- Weakening CSRF, allowed-host/origin checks, session auth, Redis TLS/auth,
  WAF/edge protections, ADR guard, import-linter, or CI to make the load test
  easier.

## Non-Goals

- Do not implement the scoring redesign in this preflight.
- Do not change CTFd sync, CTFd scoring, CTFd infrastructure, or the #846 live
  event capacity audit.
- Do not resize infrastructure, change autoscaling, add app metrics emitters,
  add public diagnostics, or create a new observability platform as part of the
  native CTF scoring decision.
- Do not add a new Ground Control requirement; issue #850 is the authoritative
  contract for this requirement-free run.
- Do not add a generic async worker, queue, notification system, cache
  framework, exception hierarchy, DTO/schema layer, or repository abstraction
  unless the measured evidence requires that cross-cutting surface.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must run the #926 harness validation for the native
CTF profile and the stack-native checks for any touched app, workflow,
Terraform, or Kubernetes surfaces.
