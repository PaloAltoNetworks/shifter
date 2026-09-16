---
id: CTF-1404
title: "Solve History Visibility"
status: ACTIVE
type: FUNCTIONAL
priority: MUST
wave: 2
created_at: 2026-07-02T01:00:00.023436Z
updated_at: 2026-07-02T06:16:27.429121Z
---

# CTF-1404: Solve History Visibility

## Statement

Participant solve history, the specific challenges a participant has solved, shall be visible only to that participant and to the event organizer. The public individual scoreboard (CTF-401) shall continue to expose aggregate ranking data (rank, display name, total score, solve count, and last-solve time) to all participants, but one participant's per-challenge solve history shall not be exposed to other participants unless the participant explicitly chooses to share it. Any solve-history projection shall be correct-solves-only and shall never expose submitted flag values, incorrect-attempt details, or attempt source IP addresses. This requirement clarifies and supersedes the literal "click a row to see that participant's solve history" clause of CTF-401, which read as exposing any participant's solve history to all participants. Governing decision: ADR-028.

## Rationale

Aggregate competitive standing (rank, score, solves, last solve) is inherently public on a scoreboard, but the specific set of challenges a participant has solved is sensitive: it reveals a competitor's skill areas and progress and enables targeting or collusion inference. It is nobody's business except the participant and the event organizer, unless the participant elects to share. Exposing every participant's per-challenge history to all participants (the literal reading of CTF-401's drill-down clause) is a privacy over-share; the semi-private posture (own participant + organizer) is the deliberate product decision. See ADR-028 and docs/architecture/ctf-scoreboard-contract-preflight-521.md.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (participant_solve_history view: own-participant-or-organizer gate + frozen-scoreboard cutoff (PR #1304))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/submission.py` (get_participant_solve_history: correct-solves-only, secret-safe projection with freeze cutoff (PR #1304))
- IMPLEMENTS → ADR `docs/adr/index.yaml::ADR-028` (ADR-028: CTF participant solve history is semi-private (participant and organizer only))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoreboard_views.py` (Solve-history view tests: own/other/organizer gate, 404, frozen-owner/organizer cutoff (PR #1304))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_submission_service.py` (get_participant_solve_history tests: correct-only, secret-safe, freeze-cutoff (PR #1304))
- IMPLEMENTS → GITHUB_ISSUE `521` (Issue #521 - Repair participant scoreboard wiring and add solve-history drill-down)
