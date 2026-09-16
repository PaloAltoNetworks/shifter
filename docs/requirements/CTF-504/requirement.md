---
id: CTF-504
title: "Team Invite Codes"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.646275Z
updated_at: 2026-03-26T06:38:10.653326Z
---

# CTF-504: Team Invite Codes

## Statement

The system should generate unique, shareable invite codes for each team that prospective members can use to join. Captains shall be able to regenerate invite codes to invalidate previous ones. Invite codes shall be single-use or multi-use (configurable). Expired or regenerated codes shall be rejected.

## Rationale

Invite codes provide a simple, shareable mechanism for team formation without requiring organizer approval for each join. For Shifter, consultants can share codes via Slack or email to quickly assemble teams before an event. (CTFd uses invite tokens for team membership.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFTeam.invite_code - unique field with auto-generation on save)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#647` (CTF-504: Team Invite Codes)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (team_join view - join via invite code with is_full check)
