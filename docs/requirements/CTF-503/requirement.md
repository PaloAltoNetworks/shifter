---
id: CTF-503
title: "Team Captains"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.611975Z
updated_at: 2026-03-26T06:38:09.740224Z
---

# CTF-503: Team Captains

## Statement

The system should designate one member per team as captain. The captain shall have the ability to: rename the team, remove members, transfer captaincy to another member, and dissolve the team (if no solves have been recorded). Organizers shall be able to reassign captaincy.

## Rationale

Teams need a designated manager for administrative actions. Without a captain role, every team change requires organizer intervention, which does not scale for events with many teams. (CTFd supports team captains with management privileges.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFTeam.captain FK field - data model only, no captain actions implemented)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/admin.py` (Django admin exposes captain field for organizer reassignment (partial))
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#646` (CTF-503: Team Captains)
