---
id: CTF-408
title: "Per-User Score Timeline"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T07:23:21.766014Z
updated_at: 2026-04-02T01:35:10.742513Z
---

# CTF-408: Per-User Score Timeline

## Statement

The system could display a per-participant score progression graph showing cumulative score over the event duration. The timeline shall plot each solve as a step increase at the timestamp of submission. Participants could view their own timeline; organizers could view any participant's timeline.

## Rationale

Score timelines help participants and organizers understand performance patterns, early bursts vs steady progress, plateaus where participants got stuck, and relative pacing compared to event duration. This adds analytical depth beyond the flat scoreboard ranking. (CTFd displays score graphs on user profiles.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (Scoring service - no per-user score timeline function)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (CTF URL patterns - score timeline API endpoint)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/__init__.py` (CTF services package - exports get_score_timeline)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/scoreboard.html` (Participant scoreboard - score timeline chart)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/participant_detail.html` (Admin participant detail - score timeline chart for organizers)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring.py` (TestGetScoreTimeline - 8 tests for score timeline service)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#572` (CTF-408: Per-User Score Timeline)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/api/scoreboard.py` (CTF Views - no score timeline/progression endpoint exists)
