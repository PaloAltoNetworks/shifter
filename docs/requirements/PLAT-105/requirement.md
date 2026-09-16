---
id: PLAT-105
title: "WebSocket Notification Infrastructure"
status: ACTIVE
type: FUNCTIONAL
priority: COULD
wave: 3
created_at: 2026-03-26T06:09:43.562639Z
updated_at: 2026-06-03T22:51:55.639651Z
---

# PLAT-105: WebSocket Notification Infrastructure

## Statement

The platform could provide a shared WebSocket notification infrastructure for delivering real-time events to connected browser clients. The infrastructure shall support: topic-based subscriptions, authenticated connections, and queuing of missed events for delivery on reconnection. Platform features shall register notification types and handlers with the shared infrastructure.

## Rationale

Multiple platform features need real-time push to browsers, range status updates, CTF score changes, provisioning progress. Mission Control already has WebSocket consumers for SSH and range status. A shared infrastructure avoids each feature building its own WebSocket layer.

## Traceability

- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#679` (PLAT-105: WebSocket Notification Infrastructure)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/notifications.py` (Shared WebSocket notification registry and publisher)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/consumers.py` (Shared authenticated notification WebSocket consumer)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/models.py` (Durable WebSocket notification queue model)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_notifications.py` (Shared notification registry and queue tests)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_notification_consumer.py` (Shared notification WebSocket consumer tests)
- IMPLEMENTS → PULL_REQUEST `Brad-Edwards/shifter#861` (Add shared WebSocket notifications)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/routing.py` (Shared notification WebSocket route)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/asgi.py` (ASGI WebSocket routing integration)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/management/commands/prune_notifications.py` (Notification queue pruning command)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/migrations/0001_initial.py` (WebSocket notification database migration)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/channels/groups.py` (Shared notification channel group helpers)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py` (Django Channels notification configuration)
- VERIFIES → PULL_REQUEST `Brad-Edwards/shifter#866` (Follow up websocket notification Sonar coverage)
