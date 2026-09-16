---
id: PLAT-102
title: "API Token Authentication"
status: ACTIVE
type: INTERFACE
priority: SHOULD
wave: 2
created_at: 2026-03-26T06:09:24.227792Z
updated_at: 2026-06-23T06:18:35.043014Z
---

# PLAT-102: API Token Authentication

## Statement

The platform shall support API authentication via session cookies (for browser-based clients) and scoped API tokens (for programmatic access). Tokens shall support configurable scopes to restrict access to specific resources and operations. Token generation and revocation shall be available via the admin UI. All non-public API endpoints shall require authentication.

## Rationale

Programmatic API access enables scripts, integrations, and automation workflows across all platform features, not just CTF. Scoped tokens follow the principle of least privilege. The platform already has API key authentication in risk_register; this extends it platform-wide with scope support.

## Traceability

- TESTS → TEST `shifter/shifter_platform/tests/cms/test_preparation_api.py` (Preparation session and scoped-token authentication with independent administrative authority)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#677` (PLAT-102: API Token Authentication)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/models.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/authentication.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/scopes.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/permissions.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/admin.py`
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py`
- IMPLEMENTS → DOCUMENTATION `docs/architecture/api-token-authentication-677.md`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_model.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_auth.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_scopes.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_admin.py`
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_vpn_profile_api.py` (Mission Control VPN profile session and scoped-token authentication tests)
