---
id: CTF-501
title: "Team Mode Toggle"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.539243Z
updated_at: 2026-03-26T06:37:59.861516Z
---

# CTF-501: Team Mode Toggle

## Statement

The system should support a per-event configuration option to enable or disable team mode. When team mode is disabled, all scoring and rankings shall operate on individual participants. When enabled, participants shall be required to join or create a team before submitting flags. The team mode setting shall be locked once the event transitions to active state.

## Rationale

Not all CTF events are team-based, some are individual competitions. Organizers need a per-event toggle to match the event format. Locking the mode after event start prevents mid-competition confusion where some participants have teams and others do not. (CTFd supports both modes as a per-event setting.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFEvent.team_mode field (line 279))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#644` (CTF-501: Team Mode Toggle)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (Scoreboard view team_mode branching (line 373))
