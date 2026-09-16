---
id: CTF-1203
title: "Webhooks"
status: DRAFT
type: INTERFACE
priority: COULD
wave: 2
created_at: 2026-03-18T05:28:24.170296Z
updated_at: 2026-03-19T03:07:20.316593Z
---

# CTF-1203: Webhooks

## Statement

The system could support configurable webhook notifications that POST JSON payloads to registered URLs when specified events occur (flag solve, first blood, event state change, new registration). Webhook endpoints shall be configurable per event by organizers. The system shall retry failed deliveries with exponential backoff. Webhook payloads shall include event type, timestamp, and relevant entity data.

## Rationale

Webhooks enable real-time integration with external systems like Slack (solve announcements), external scoreboards, or analytics platforms without polling the API. This is a push-based complement to the pull-based REST API. While lower priority than the API itself, webhooks significantly reduce integration complexity.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTF models - no WebhookConfig or webhook-related model exists)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#635` (CTF-1203: Webhooks)
