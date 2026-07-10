# CTF Tie-Breaking Test Traceability Preflight (#539 / CTF-406)

Status: pre-implementation guidance

Date: 2026-06-28

Requirement: `CTF-406` - Tie-Breaking Rules

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/539>

This note is intentionally not an implementation plan. The issue is about
meaningful automated coverage and Ground Control `TESTS` traceability for the
existing deterministic scoreboard tie-breaker. It is not a mandate to redesign
scoring, add configurable ranking modes, or move ranking logic into views.

## Scope Boundary

`CTF-406` is satisfied by the existing scoring service contract:

- rank by total score descending;
- when total score ties, rank the row with the earlier most-recent correct solve
  timestamp higher;
- if both score and last-solve timestamp match, share the competition rank;
- participants or teams with no solves sort after rows with solves for the same
  score;
- participant-facing help text documents the rule.

The traceability work should prove this behavior where it already lives. Do not
create a parallel scoreboard schema, client-side ranking path, or extra
tie-breaker abstraction for this issue.

## Architecture Decisions And Guardrails

- Treat `ctf.services.scoring` as the single public scoring boundary. The
  package re-exports public names from `ctf/services/scoring/_read.py` and
  `_maintenance.py`; avoid adding imports against an obsolete
  `ctf/services/scoring.py` file path.
- The authoritative data remains `CTFSubmission` correct rows and `CTFAward`
  rows. The live scoreboard reads materialized `cached_score`,
  `cached_solve_count`, and `last_solve_at`; frozen and some bracket-filtered
  paths recompute from source rows. Coverage should not encode a separate
  ranking algorithm in fixtures.
- Eligibility remains shared through
  `ctf.services.participant.eligible_participant_q()`. A disqualified or
  unregistered participant must not reappear in tie-breaker coverage.
- HTML, DRF, and legacy JSON surfaces consume rows from `get_scoreboard()` or
  `get_team_scoreboard()`. Views/templates may display rank, score, solve count,
  and last solve; they must not sort or re-rank rows.
- The visible documentation surface is the participant help template. If tests
  cover documentation, assert participant-visible wording without coupling to a
  full rendered page snapshot.
- Ground Control `TESTS` links must point at maintained behavior tests, not at
  this preflight note, audit docs, broad smoke tests, or placeholders.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for CTF-406 coverage |
| --- | --- | --- |
| Scoring API | `ctf.services.scoring.get_scoreboard`, `get_team_scoreboard`, `get_participant_rank` | Exercise public service functions; do not call private row builders as the primary proof. |
| Ranking implementation | `ctf/services/scoring/_read.py` | Preserve score-descending plus earliest-last-solve ordering and shared-rank behavior. |
| Null solve ordering | `_nulls_last()` / `_RANK_NULL_LAST` | Do not rely on database-specific NULL ordering; SQLite and PostgreSQL differ. |
| Materialized state | `CTFParticipant.last_solve_at`, `CTFTeam.last_solve_at`, `cached_score`, `cached_solve_count` | Use recompute helpers or existing write services to maintain cached state; do not hand-update cached columns except in narrow corruption/rebuild tests. |
| Source-of-truth rebuild | `recompute_participant_score`, `recompute_team_score`, `recompute_event_leaderboard`, `ctf_recompute_leaderboard` | A live-board assertion should stay consistent with authoritative recompute. |
| Participant eligibility | `ctf.services.participant.eligible_participant_q()` | Reuse the shared scoring/access predicate; do not duplicate status lists in tests or views. |
| Bracket filter parsing | `ctf.views._parsing._resolve_bracket_filter()` | Keep bracket selection in the existing helper; no new UUID parser or query schema. |
| Access gates | `@login_required`, `ctf_participant_required`, `ctf_organizer_required`, event ownership checks, `PublicScoreboardView` | Do not add a new scoreboard endpoint or weaken existing visibility/ownership behavior. |
| Error envelopes | `ctf.api._base._canonical_error_response`, `shared.api.errors`, `ctf.views._access._json_error()` | Keep public API failures in existing controlled envelopes. |
| Logging hygiene | module loggers, `shared.log_sanitize.safe_log_value()` | Tie-breaker tests should not introduce logging of flags, invite tokens, secrets, or raw provider payloads. |
| Test style | `shifter/shifter_platform/tests/ctf/test_scoring.py` | Prefer real-DB scoring behavior tests; mocked tests are secondary for narrow call-chain invariants. |

## Cross-Cutting Layers

- Auth surface: participant HTML scoreboards stay behind `login_required` and
  `ctf_participant_required`, using the active-event participant resolution.
  Organizer scoreboards stay behind `ctf_organizer_required` plus event ownership.
  The DRF public scoreboard is intentionally anonymous and must expose only the
  existing public scoreboard payload.
- Secret-handling surface: scoreboards and tests should use participant/team ids,
  names, ranks, scores, solve counts, and timestamps only. Do not log or assert
  raw submitted flags, invite tokens, API tokens, email bodies, or cloud/provider
  data.
- Env-binding and config shape: CTF-406 requires no environment variable, Django
  setting, feature flag, or deployment config. Do not add one for traceability.
- Request validation: the only request input in scope is the existing `bracket`
  query parameter, resolved by `_resolve_bracket_filter()`. Scoreboard ranking
  must not depend on unvalidated client-provided sort fields.
- Persistence: the persistent ranking fields are the existing materialized
  columns and indexes on participant/team score plus `last_solve_at`; the source
  of truth remains submissions and awards. No schema change is needed unless the
  implementation uncovers a real behavior gap.
- OS/runtime exposure: this work should not add CLI flags, process argv values,
  temp files, scheduler jobs, or management commands. The existing
  `ctf_recompute_leaderboard` command is the rebuild path.
- Error envelopes and leakage: hidden or missing scoreboards must keep existing
  `scoreboard_hidden`, 404, and canonical API error behavior. Do not expose
  traceback text, SQL details, or raw exception strings.
- Observability: use existing module loggers if needed. Prefer durable state and
  service-return assertions over brittle full-message log snapshots.

## Extensibility Seam

The seam is the service-level ranking key, parameterized by the existing read
mode inputs: `freeze_at`, `bracket_id`, and individual versus team aggregation.
Future ranking variations, if product requirements introduce them, belong in the
scoring service and persisted event/scoring contract, not in templates,
JavaScript, serializers, or Ground Control metadata.

Coverage can be parameterized over live materialized reads and authoritative
recompute reads so the next read-path variation does not require copying a new
fixture-level ranking model.

## Gotchas And Anti-Patterns

- Do not conflate "earliest last solve wins" with "first solve wins". The
  tie-breaker is the timestamp of the most recent correct solve that produced the
  participant's solved state.
- Do not use award `created_at` as a CTF-406 tie-breaker. Awards contribute to
  score, but the current requirement names most-recent solve time.
- Do not sort null `last_solve_at` values according to backend defaults.
  PostgreSQL and SQLite differ; `_nulls_last()` is the canonical guard.
- Do not sort in templates, JavaScript, API serializers, or tests after receiving
  service rows. That hides service regressions and creates a second ranking path.
- Do not create duplicate participant status enums, score DTOs, validation
  helpers, exception classes, or API error shapes for this test/traceability work.
- Do not treat a broad API smoke test as meaningful CTF-406 coverage unless it
  asserts rank order and participant-visible documentation.
- Do not create `TESTS` links to stale source paths, especially the pre-package
  `ctf/services/scoring.py` path, if the maintained code lives under
  `ctf/services/scoring/`.

## Non-Goals

- No scoring redesign, dynamic scoring mode, configurable tie-breaker, award
  semantics change, rank-display redesign, or client-side sorting feature.
- No new public API surface, serializer schema, database migration, management
  command, scheduler behavior, deployment config, or environment variable.
- No changes to CTF access-control policy, event visibility, bracket semantics,
  challenge statistics, range provisioning, notifications, or Ground Control
  `IMPLEMENTS` links are required for this preflight.
