---
id: CTF-404
title: "Scoreboard Visibility Controls"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:22.393914Z
updated_at: 2026-03-26T06:37:47.063667Z
---

# CTF-404: Scoreboard Visibility Controls

## Statement

The system should support controlling scoreboard visibility with at least three modes: public (visible to anyone), participants-only (visible only to registered participants and organizers), and hidden (visible only to organizers). The visibility mode shall be configurable per event and changeable at any time.

## Rationale

Not all CTF events should have public scoreboards, internal training events may want results restricted to participants, and practice events may hide scores entirely to focus on learning. For Shifter, enterprise events involving PANW customers should restrict scoring data to participants only. (CTFd supports similar visibility controls.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF Models - CTFEvent lacks scoreboard_visibility field)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#643` (CTF-404: Scoreboard Visibility Controls)
- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (CTF Views - scoreboard view has no visibility access control)
