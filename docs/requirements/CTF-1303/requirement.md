---
id: CTF-1303
title: "Custom Pages"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.273081Z
updated_at: 2026-03-19T03:07:30.082368Z
---

# CTF-1303: Custom Pages

## Statement

The system could support creating custom informational pages per event with Markdown content. Custom pages could include: rules, FAQ, getting started guide, or sponsor information. Pages shall be accessible from the event navigation. Organizers shall be able to create, edit, and delete custom pages.

## Rationale

Custom pages provide a place for event-specific information that does not fit in the challenge descriptions or announcements. CTFd supports custom pages. For Shifter, a getting-started page explaining how to access ranges and use Guacamole would reduce support requests during events.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF models - no CustomPage or custom page model exists)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#637` (CTF-1303: Custom Pages)
