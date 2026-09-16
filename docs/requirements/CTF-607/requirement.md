---
id: CTF-607
title: "Admin Roles (Moderator/Judge)"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:22.980327Z
updated_at: 2026-03-26T06:38:37.230621Z
---

# CTF-607: Admin Roles (Moderator/Judge)

## Statement

The system could support additional administrative roles beyond organizer: moderator (can manage participants and announcements but not challenges or scoring) and judge (can view all submissions and grant awards but not modify event configuration). These roles shall be assignable per event by organizers.

## Rationale

Large CTF events often have support staff who need some admin capabilities without full organizer access. For Shifter events with multiple organizers, role granularity prevents accidental configuration changes by support staff. (CTFd supports multiple admin tiers.)

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/event_staff.py` (Event-scoped moderator, judge, and co-organizer assignment model)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#656` (CTF-607: Admin Roles (Moderator/Judge))
