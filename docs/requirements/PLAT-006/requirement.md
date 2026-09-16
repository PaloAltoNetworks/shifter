---
id: PLAT-006
title: "Cloud-Agnostic Data Model"
status: ACTIVE
type: CONSTRAINT
priority: MUST
wave: 1
created_at: 2026-03-19T02:57:49.045281Z
updated_at: 2026-05-03T14:19:16.389310Z
---

# PLAT-006: Cloud-Agnostic Data Model

## Statement

The application data model and business logic shall not contain cloud-provider-specific references such as ARNs, S3 bucket paths, or AWS account IDs. Cloud-specific identifiers shall be resolved at the infrastructure integration layer, not stored in domain models or passed through business logic. Where cloud resource references must be persisted (for example, object storage paths), the system shall use provider-neutral identifiers that are resolved to cloud-specific URIs at access time.

## Rationale

Cloud-specific references embedded in the data model create invisible coupling that prevents portability. A database full of S3 ARNs cannot be moved to GCP without data migration. Provider-neutral identifiers ensure the data layer is portable and that switching or adding cloud providers does not require schema changes or data transformations.

## Traceability

- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/engine/models/_range.py` (Range model - stores AWS ARNs (kali_ssh_key_secret_arn, step_function_execution_arn), EC2 instance IDs, subnet IDs directly in fields)
- IMPLEMENTS → CODE_FILE `shifter/shifter_platform/cms/models/assets.py` (FileAsset model - s3_key field hardcoded as S3 object key, not provider-neutral storage path)
- DOCUMENTS → GITHUB_ISSUE `Brad-Edwards/shifter#675` (PLAT-006: Cloud-Agnostic Data Model)
