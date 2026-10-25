---
id: CTF-608
title: "Magic Link Authentication"
status: DEPRECATED
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-03-18T05:28:23.014026Z
updated_at: 2026-04-06T03:40:18.824260Z
---

# CTF-608: Magic Link Authentication

## Statement

Historical requirement, retired by #1206's isolated-account migration. For
#2316 the maintainer confirmed preservation of current login and password
recovery, not restoration of magic-link authentication. The historical statement
below is superseded by CTF-006 and does not describe a current endpoint.

CTF participant onboarding shall use the platform's passwordless authentication (PLAT-101) for external users who do not have corporate SSO access. The CTF invitation flow shall generate magic links that authenticate the recipient and associate them with the target CTF event. The CTF layer shall not implement its own authentication mechanism.

## Rationale

Authentication is a platform capability. CTF composes with PLAT-101 for participant onboarding rather than building its own auth system. Internal users authenticate via OIDC/SSO as usual.

## Traceability

- DOCUMENTS → CODE_FILE `shifter/shifter_platform/ctf/migrations/0033_isolated_participant_accounts.py` (Retirement of invite-token authentication and fields)
- DOCUMENTS → DOCUMENTATION `docs/features/access-credentials.md` (Current login/recovery and explicit retirement)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#584` (Historical magic-link implementation)
