---
id: PLAT-101
title: "Passwordless Authentication (Magic Links)"
status: DEPRECATED
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-26T06:09:19.279433Z
updated_at: 2026-04-06T04:55:03.932967Z
---

# PLAT-101: Passwordless Authentication (Magic Links)

## Statement

Historical requirement, retired by #1206's isolated-account migration. For
#2316 the maintainer confirmed preservation of current login and password
recovery, not restoration of magic-link authentication. The historical statement
below is superseded by CTF-006 and does not describe a current endpoint.

The platform shall support passwordless authentication via magic links sent to user email addresses. A magic link shall be a single-use, time-limited URL that authenticates the user and establishes a session. Magic links shall expire after a configurable duration (default 24 hours). The platform shall rate-limit magic link generation to prevent abuse. Magic link authentication shall be available alongside the existing OIDC/SSO authentication for users who do not have corporate SSO access.

## Rationale

External users (customers, partners, CTF participants) need a frictionless authentication path that does not require corporate SSO enrollment. Magic links eliminate password management friction for users who may only access the platform occasionally. This is a platform-wide capability used by CTF participant onboarding and potentially other features.

## Traceability

- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0033_isolated_participant_accounts.py` (Retirement of invite-token authentication and fields)
- DOCUMENTS → DOCUMENTATION `docs/features/access-credentials.md` (Current login/recovery and explicit retirement)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#585` (Historical magic-link implementation)
