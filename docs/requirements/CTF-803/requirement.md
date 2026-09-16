---
id: CTF-803
title: "Announcements"
status: DRAFT
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.358552Z
updated_at: 2026-03-26T06:38:46.487469Z
---

# CTF-803: Announcements

## Statement

The system should support organizer announcements that are visible to all event participants. Announcements shall have a title, body (Markdown), and timestamp. Announcements shall be displayed prominently in the event UI (for example banner or dedicated panel). Participants shall be able to view all past announcements for the current event. Announcements shall optionally trigger email or real-time notifications.

## Rationale

Announcements are the organizer's broadcast channel during live events for communicating rule clarifications, hint releases, schedule changes, or infrastructure issues. Without a formal announcement system, organizers resort to ad-hoc communication that may not reach all participants. (CTFd supports a similar announcements feature.)

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#666` (CTF-803: Announcements)
