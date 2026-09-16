---
id: PLAT-103
title: "Email Templating and Delivery Service"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-26T06:09:28.301270Z
updated_at: 2026-04-05T16:17:36.233197Z
---

# PLAT-103: Email Templating and Delivery Service

## Statement

The platform shall provide a shared email templating and delivery service. Templates shall support variable substitution for dynamic content (user name, event details, URLs, dates). Default templates shall be provided for common notification types. The service shall send emails asynchronously without blocking the triggering action. Failed delivery shall be logged but shall not affect the triggering operation.

## Rationale

Multiple platform features (CTF notifications, range readiness alerts, account management) need to send templated emails. A shared email service avoids each feature implementing its own email rendering and delivery logic. Consistent email formatting and reliable delivery are platform-wide concerns.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/email.py` (Shared email templating and delivery service (render_template, send_email, send_email_async))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py` (CTF notification service, delegates to shared.email for rendering and delivery)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_email.py` (Tests for shared email service (render, send, async))
- IMPLEMENTS → GITHUB_ISSUE `581`
- TESTS → TEST `tests/ctf/test_services/test_notification.py` (CTF notification async-delivery tests (PLAT-103 clause 3))
- TESTS → TEST `tests/ctf/test_services/test_notification_helpers.py` (CTF notification helper/render tests (PLAT-103))
