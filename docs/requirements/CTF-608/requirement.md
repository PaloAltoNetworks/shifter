---
id: CTF-608
title: "Magic Link Authentication"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.014026Z
updated_at: 2026-04-06T03:40:18.824260Z
---

# CTF-608: Magic Link Authentication

## Statement

CTF participant onboarding shall use the platform's passwordless authentication (PLAT-101) for external users who do not have corporate SSO access. The CTF invitation flow shall generate magic links that authenticate the recipient and associate them with the target CTF event. The CTF layer shall not implement its own authentication mechanism.

## Rationale

Authentication is a platform capability. CTF composes with PLAT-101 for participant onboarding rather than building its own auth system. Internal users authenticate via OIDC/SSO as usual.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/participant.py` (invite_participant and _auto_register_participant, user creation and token generation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/services/notification.py` (send_invitations and _build_registration_url, magic link email delivery)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFParticipant model, invite_token, invite_token_expires, is_invite_valid)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/urls.py` (CTF URL routes, ctf_register endpoint)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/settings.py` (AUTHENTICATION_BACKENDS, platform ModelBackend used for magic link login)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_auth.py` (CTF auth tests, magic link token authentication)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_participant.py` (Participant service tests, invite_participant, _auto_register_participant)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_services/test_notification.py` (Notification service tests, send_invitations, magic link URL building)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_models.py` (CTF model tests, invite_token generation and is_invite_valid)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#584` (CTF-608: Magic Link Authentication)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (ctf_register view, magic link token authentication endpoint)
