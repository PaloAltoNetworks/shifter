---
id: CTF-802
title: "Real-Time Notifications"
status: DRAFT
type: FUNCTIONAL
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:23.323699Z
updated_at: 2026-03-26T06:10:13.736995Z
---

# CTF-802: Real-Time Notifications

## Statement

CTF events could deliver real-time in-app notifications using the platform's WebSocket infrastructure (PLAT-105). CTF-specific notification types include: new challenge released, announcement posted, scoreboard position change, and first blood achieved. Notifications shall be displayed as non-blocking toasts or a notification panel. Participants who are not connected shall receive notifications upon next connection.

## Rationale

Real-time notification delivery is a platform capability. Mission Control already has WebSocket consumers. CTF registers its notification types with PLAT-105 rather than building a separate WebSocket layer.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#665` (CTF-802: Real-Time Notifications)
