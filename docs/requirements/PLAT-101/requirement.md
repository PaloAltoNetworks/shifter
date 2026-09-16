---
id: PLAT-101
title: "Passwordless Authentication (Magic Links)"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-26T06:09:19.279433Z
updated_at: 2026-04-06T04:55:03.932967Z
---

# PLAT-101: Passwordless Authentication (Magic Links)

## Statement

The platform shall support passwordless authentication via magic links sent to user email addresses. A magic link shall be a single-use, time-limited URL that authenticates the user and establishes a session. Magic links shall expire after a configurable duration (default 24 hours). The platform shall rate-limit magic link generation to prevent abuse. Magic link authentication shall be available alongside the existing OIDC/SSO authentication for users who do not have corporate SSO access.

## Rationale

External users (customers, partners, CTF participants) need a frictionless authentication path that does not require corporate SSO enrollment. Magic links eliminate password management friction for users who may only access the platform occasionally. This is a platform-wide capability used by CTF participant onboarding and potentially other features.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/models.py` (CTFParticipant model, configurable token expiration via MAGIC_LINK_EXPIRY_HOURS)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/settings.py` (MAGIC_LINK_EXPIRY_HOURS and MAGIC_LINK_SINGLE_USE settings)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_auth.py` (Magic link auth tests, expiration, single-use, rate limiting)
- CONSTRAINS → ADR `ADR-009` (AWS and GCP keep provider-specific identity stacks behind a shared auth seam)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#585` (PLAT-101: Passwordless Authentication (Magic Links))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/participant.py` (ctf_register view, token expiration enforcement, rate limiting helper)
