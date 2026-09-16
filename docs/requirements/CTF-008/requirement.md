---
id: CTF-008
title: "Notifications & Communications"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:21.159679Z
updated_at: 2026-09-05T00:00:00Z
---

# CTF-008: Notifications & Communications

## Statement

The CTF layer should keep participants informed of event milestones and organizer communications through the platform's email service (PLAT-103) and optional real-time in-app notifications via the platform's WebSocket infrastructure (PLAT-105).

## Rationale

Communication keeps participants informed and engaged before, during, and after events. Email notifications are critical for Shifter consultants who may not be actively watching the platform when events start or ranges become available. CTF defines the notification triggers and content; the platform provides the delivery infrastructure.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py` (CTF Notification service (email: invitations, credentials, reminders, announcements, scheduling))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py (CTFNotification)` (CTFNotification model (type, status, scheduling, recipient filtering, sent tracking))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views.py (notification views)` (Notification views: admin_notification_list, admin_notification_create, api_notification_list, api_notification_send, api_send_invitations)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/templates/ctf/email/` (Email templates: invitation, credentials, reminder, announcement (HTML + text))
- TESTS → TEST `shifter/shifter_platform/ctf/tests/test_services/test_notification.py` (Notification service tests (invitations, credentials, reminders, announcements, scheduling, rendering))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models/communication.py` (Scoped communication domain models (ADR-051, #2048): campaigns, immutable message revisions, normalized intents, recipient snapshots, delivery attempts, participant receipts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/` (Communication service contracts: audience resolution, campaign authoring, atomic intent release, lifecycle, retention)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_services.py` (Cross-event confinement, audience resolution, and atomic-release idempotency tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2048` (Model scoped communication campaigns, audiences, content, and deliveries)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/delivery.py` (Lease-based delivery worker (ADR-051-R12, #2098): claim/lease/fence, bounded retry-backoff, elapsed ceiling, stale-lease recovery, partial-failure isolation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/adapters/` (Channel adapter command/result contract and the in-app reference-only wake-up adapter (#2098); email transport is completed by #1525)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/backpressure.py` (Admission backpressure (#2098): fixed-window rate limits plus durable outstanding-work reservations and a fan-out cap)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/communication/metrics.py` (Fail-soft delivery-engine operator metrics with closed low-cardinality labels (#2098))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/management/commands/drain_ctf_communication_deliveries.py` (Supervised delivery worker command with heartbeat and graceful shutdown (#2098))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_delivery.py` (Delivery worker, in-app channel, wake-up stable identity, fencing, retry, and expiry tests (#2098))
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_communication_delivery_postgres.py` (PostgreSQL concurrency proofs: no double-claim, fair batching, stale-lease fencing (#2098))
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#2098` (Durable delivery worker and in-app channel for scoped communications)
