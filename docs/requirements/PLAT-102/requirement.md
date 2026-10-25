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

The platform shall support session-cookie authentication with CSRF, Knox-backed personal tokens, and renewable native GCP service credentials. Every credential shall resolve an explicit active principal and immutable action ceiling; scopes do not replace live application authorization. Personal-token issuance and use require a live grant, finite expiry and current authority for the requested actions. Session-authenticated owners can issue, rotate and revoke through the credential management API/UI, and can revoke their own tokens after losing issuance rights. Bearers cannot issue or rotate personal tokens. Service principals are independent of their human creator/contact; native application ID tokens and cloud access tokens remain distinct. Invalid bearer proof shall never fall through to a session. All non-public API endpoints shall require authentication.

## Rationale

Personal credentials are bound to the exact target type and UUID authorized at
issuance. That immutable target remains part of the credential ceiling at use;
an owner gaining access to another resource does not expand an existing token.

Programmatic API access enables scripts, integrations, and automation workflows across platform features. Credential ceilings and independent live authorization follow least privilege. Knox owns personal proof; native Google libraries own service proof and renewal, without an application-managed token protocol.

## Traceability

- TESTS → TEST `shifter/shifter_platform/tests/workspaces/test_authorization_api.py` (Personal credential issuance-target confinement at the HTTP boundary)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/authorization/contracts.py` (Independent immutable action and target ceilings)

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/personal_credentials.py` (Live-granted personal issuance, rotation and owner revocation)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/management/service_credentials.py` (Independent service admission and lifecycle)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/config/service_identity.py` (Native exact-audience service verification)
- IMPLEMENTS → CODE_FILE `shifter/shifter_client/__init__.py` (Separate automatically renewable native app/cloud transports)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/frontend/src/features/credentials/AccessCredentialsPage.tsx` (Session credential management and volatile one-time delivery)
- TESTS → TEST `shifter/shifter_platform/tests/management/test_credential_api.py`
- TESTS → TEST `shifter/shifter_platform/tests/management/test_credential_rotation_postgres.py`
- TESTS → TEST `shifter/shifter_platform/tests/config/test_service_client.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_credential_db_guards.py`
- DOCUMENTS → DOCUMENTATION `docs/technical/shifter_platform/access-credentials.md`

- TESTS → TEST `shifter/shifter_platform/tests/cms/test_preparation_api.py` (Preparation session and scoped-token authentication with independent administrative authority)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#677` (PLAT-102: API Token Authentication)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/models.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/authentication.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/scopes.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/permissions.py`
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/admin.py`
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py`
- DOCUMENTS → DOCUMENTATION `docs/architecture/api-token-authentication-677.md` (Historical verifier decision superseded by #2316)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_model.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_auth.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_scopes.py`
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_admin.py`
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_vpn_profile_api.py` (Mission Control VPN profile session and scoped-token authentication tests)
