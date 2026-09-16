---
id: CTF-505
title: "Team Size Limits"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.681595Z
updated_at: 2026-03-26T06:38:25.614146Z
---

# CTF-505: Team Size Limits

## Statement

The system should support configuring a maximum team size per event. The system shall reject join attempts when a team is at capacity. The minimum team size shall be 1 (solo in team mode). The maximum shall be configurable by organizers with no hard-coded upper limit. A value of 0 or null shall mean unlimited team size.

## Rationale

Team size limits ensure competitive balance, a team of 20 has an unfair advantage over a team of 3. For Shifter events, organizers may want to enforce balanced teams of 3-5 to ensure everyone participates rather than one expert carrying a large team. (CTFd supports team size configuration.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFEvent.team_size_limit field and CTFTeam.is_full property)
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_models.py` (TestCTFTeamModel.test_team_is_full - verifies is_full at capacity)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#648` (CTF-505: Team Size Limits)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (team_join view - rejects join when team.is_full)
