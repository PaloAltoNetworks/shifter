---
id: PLAT-106
title: "Unified DRF API Surface"
status: ACTIVE
type: CONSTRAINT
priority: SHOULD
wave: 2
created_at: 2026-06-23T00:41:58.002548Z
updated_at: 2026-06-25T02:41:49.102085Z
---

# PLAT-106: Unified DRF API Surface

## Statement

All non-public platform HTTP/JSON API endpoints shall be served through Django REST Framework (DRF) and shall enforce the platform's API authentication and scope-based authorization established by PLAT-102: session-cookie authentication with CSRF for browser/SPA clients, and scoped API tokens for programmatic clients. Each endpoint shall declare its required scopes from the central scope registry. Application logic shall remain in the service layer; the DRF layer shall own only HTTP concerns (authentication, scope authorization, serialization/validation, error envelope, pagination). Ad-hoc Django function-view JSON endpoints outside DRF (Mission Control, CTF, CMS) shall be migrated onto this surface. The platform API shall expose an OpenAPI schema.

## Rationale

PLAT-102 establishes the token + scope authentication foundation, but the platform currently has two divergent API styles: DRF (risk_register /api/v1) and ad-hoc Django function views (Mission Control, CTF, CMS). A single DRF-based API surface gives one authentication/authorization path, consistent error and pagination contracts, and an OpenAPI schema, the foundation a future SPA frontend and external integrations both consume over the same contract. Consolidating early, before the SPA is built, avoids migrating endpoints out from under a live frontend and removes a class of per-endpoint security retrofits. Business logic already lives in the service layer, so migration re-houses the HTTP layer rather than rewriting behavior.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/api/artifact_preparation.py` (Preparation lifecycle DRF endpoints with service-owned application logic)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/api/preparation_adapters.py` (Private adapter administration through scoped DRF endpoints)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_preparation_api.py` (Preparation authentication, scopes, CSRF and rejected executable overrides)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1122` (PLAT-106: Migrate CMS (experiments + scenario editor) JSON API to DRF + scoped auth)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1119` (PLAT-106: Establish platform DRF API conventions and OpenAPI schema)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/_drf_settings.py` (Platform DRF defaults, schema, pagination, and local docs assets)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/api_urls.py` (Versioned API route surface and authenticated schema/docs endpoints)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/urls.py` (Project /api/v1 mount for the platform API)
- IMPLEMENTS → CONFIG `shifter/shifter_platform/config/settings.py` (DRF and schema application registration in Django settings)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api/errors.py` (Shared platform API error envelope helpers)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api/permissions.py` (Shared scoped API permission base for DRF endpoints)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api/schema.py` (Shared OpenAPI authentication and error-envelope schema extensions)
- IMPLEMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/dev/api.md` (Developer guide for platform DRF API conventions)
- TESTS → TEST `shifter/shifter_platform/tests/config/test_api_urls.py` (Tests for authenticated schema/docs and v1 API routing)
- TESTS → TEST `shifter/shifter_platform/tests/config/test_settings.py` (Tests for platform DRF settings defaults)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_errors.py` (Tests for the shared platform API error envelope)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_permissions.py` (Tests for required-scope DRF permission behavior)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1120` (PLAT-106: Migrate Mission Control JSON API to DRF + scoped auth)
- IMPLEMENTS → PULL_REQUEST `Brad-Edwards/shifter#1202` (changed: migrate mission control apis to drf)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/api_tokens/scopes.py` (Mission Control API-token scope registry entries)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/permissions.py` (Mission Control actor and lifecycle DRF permissions)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/serializers.py` (Mission Control DRF request serializers and validation contracts)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/urls.py` (Canonical Mission Control DRF URL surface)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/_base.py` (Shared Mission Control DRF base view and error-envelope handling)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/ranges.py` (Mission Control range and catalog DRF endpoints)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/uploads.py` (Mission Control upload DRF endpoints with scoped auth)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/guacamole.py` (Mission Control Guacamole DRF bootstrap endpoints)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/resources.py` (Mission Control NGFW, credential, and script DRF endpoints)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_api_token_access.py` (Mission Control scoped API-token access tests)
- TESTS → TEST `shifter/shifter_platform/tests/shared/test_api_tokens_scopes.py` (Mission Control API-token scope registry tests)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_range_api.py` (Mission Control range DRF compatibility tests)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_views_uploads.py` (Mission Control upload DRF compatibility tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1121` (PLAT-106: Migrate CTF JSON API to DRF + scoped auth)
- IMPLEMENTS → PULL_REQUEST `Brad-Edwards/shifter#1215` (changed: migrate ctf json api to drf boundary)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/_base.py` (CTF DRF boundary helpers, actor resolution, scoped auth, and canonical error envelopes)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/urls.py` (Canonical CTF DRF API URL surface)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/api/views.py` (Canonical CTF DRF endpoint callables and public scoreboard)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/_parsing.py` (DRF body bridge for legacy CTF JSON parsers)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/ctf/views/__init__.py` (Legacy CTF API exports preserving non-canonical CSRF behavior)
- DOCUMENTS → DOCUMENTATION `docs/architecture/ctf-drf-api-preflight-1121.md` (CTF DRF API migration preflight and compatibility notes)
- TESTS → TEST `shifter/shifter_platform/tests/ctf/test_drf_api_token_access.py` (CTF scoped API-token and canonical API behavior tests)
- IMPLEMENTS → PULL_REQUEST `Brad-Edwards/shifter#1227` (changed: add CMS DRF API routes)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1122` (PLAT-106: Migrate CMS (experiments + scenario editor) JSON API to DRF + scoped auth)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/api/permissions.py` (CMS DRF actor resolution, authoring permission, and read/write scope composition)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/api/serializers.py` (CMS DRF request serializers for YAML and script upload API bodies)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/api/urls.py` (Canonical CMS DRF API route surface with experiment feature-flag gating)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/api/views.py` (CMS DRF views delegating scenario-editor and experiment API behavior to CMS services)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/scenario_editor/_validation.py` (Scenario-editor YAML validation with safe API-facing parse error text)
- DOCUMENTS → DOCUMENTATION `docs/architecture/cms-drf-api-preflight-1122.md` (CMS DRF API migration preflight and binding architecture guidance)
- DOCUMENTS → DOCUMENTATION `shifter/shifter_platform/documentation/docs/technical/dev/api.md` (Developer guide for platform and CMS DRF API conventions)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_drf_api_token_access.py` (CMS scoped API-token, session, feature-flag, YAML, and script upload DRF tests)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1124` (PLAT-106: Retire deprecated risk_register APIKey in favor of platform ApiToken)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#1244` (PLAT-106: drop dead risk_register APIKey reference from access.py (follow-up to #1124))
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/mission_control/api/_vpn.py` (Scoped Mission Control OpenVPN profile DRF endpoint)
- TESTS → TEST `shifter/shifter_platform/tests/mission_control/test_vpn_profile_api.py` (Mission Control VPN profile API authorization and delivery tests)
