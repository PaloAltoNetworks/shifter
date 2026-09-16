---
id: CTF-402
title: "Team Scoreboard"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.323485Z
updated_at: 2026-04-02T03:26:28.266516Z
---

# CTF-402: Team Scoreboard

## Statement

The system should display a team scoreboard when team mode is active, ranking teams by aggregate team score. Team score shall be the sum of all team members' individual scores. The scoreboard shall show: team rank, team name, total score, number of unique challenges solved by any team member, and team member count.

## Rationale

Team scoreboards aggregate individual efforts into a team competition. For Shifter, team mode enables consultant groups to collaborate on range-based challenges while competing against other teams. (CTFd supports team scoreboards that roll up member scores.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/admin/scoreboard.html` (Admin scoreboard template - team rankings with Members column when team_mode)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/participant/scoreboard.html` (Participant scoreboard template - has team_mode conditional but context variable mismatch)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/scoring.py` (get_team_scoreboard() - team rankings with aggregate score, solve_count, member_count)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_scoring.py` (Team scoreboard scoring tests including unique challenge solve count)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#573` (CTF-402: Team Scoreboard)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (scoreboard view and admin_scoreboard_view - call get_team_scoreboard() when team_mode)
