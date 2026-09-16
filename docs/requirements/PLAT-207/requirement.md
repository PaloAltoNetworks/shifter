---
id: PLAT-207
title: "Credential and Artifact Management"
status: ACTIVE
type: FUNCTIONAL
priority: SHOULD
wave: 2
created_at: 2026-05-09T05:11:30.280032Z
updated_at: 2026-05-09T05:11:30.292192Z
---

# PLAT-207: Credential and Artifact Management

## Statement

The platform shall provide user-scoped credential, agent file, and script/artifact management with server-side ownership checks, soft deletion where appropriate, direct object-storage upload and verification, and provider-neutral service projections so range and experiment workflows can consume credentials and assets without exposing secret material in UI or API responses.

## Rationale

Credential and artifact management is implemented across CMS and Mission Control but was not represented by a platform-level requirement.

## Traceability

- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#15` (Django: Agent config CRUD with S3 upload)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#34` (Infra: S3 bucket for user uploads)
- IMPLEMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#90` (Portal: Agent upload to S3)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#461` (SCM PINs and NGFW authcodes are stored in plaintext JSON despite the platform claiming encryption at rest)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/services.py` (Credential and upload service layer)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/assets/s3.py` (Object-storage asset helpers)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/assets/upload_token.py` (Signed upload completion tokens)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/models/assets.py` (Asset data model)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/models/catalogs.py` (Credential and asset catalog models)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/shared/schemas/credentials.py` (Provider-neutral credential projections)
- TESTS → TEST `shifter/shifter_platform/tests/cms/test_credentials.py` (Credential service tests)
- TESTS → TEST `shifter/shifter_platform/tests/cms/assets/test_s3.py` (S3 asset tests)
