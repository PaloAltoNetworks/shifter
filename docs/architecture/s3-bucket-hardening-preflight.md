# Portal User-Uploads S3 Bucket Hardening

Status: implemented controls with documented deferrals

Tracking issues:

- SSE-KMS / bucket policy: [#218](https://github.com/Brad-Edwards/shifter/issues/218)
- Cross-region replication evaluation: [#143](https://github.com/Brad-Edwards/shifter/issues/143)
- Access logging: [#310](https://github.com/Brad-Edwards/shifter/issues/310) (unified logging strategy)
- Versioning disabled: [#109](https://github.com/Brad-Edwards/shifter/issues/109)

Canonical Terraform surface: `platform/terraform/modules/portal/s3/`

## Scope

This note covers the **portal user-uploads** bucket only — presigned browser
PUT uploads for ephemeral agent and user files. It does not cover:

- Log-aggregation buckets (`platform/terraform/modules/log-aggregation/`)
- Engine/Pulumi state buckets (`platform/terraform/modules/engine-state/`)
- CMS or range asset buckets elsewhere in the repo

## Enabled Controls

| Control | Implementation |
| --- | --- |
| SSE-KMS with bucket keys (CKV_AWS_145) | `aws_s3_bucket_server_side_encryption_configuration` with env-root CMK |
| TLS-only access | Bucket policy `DenyNonTLSRequests` |
| CMK-only writes | Bucket policy denies PUT without `aws:kms` and wrong key |
| Public access block | All four block flags enabled |
| CORS | Presigned PUT allowlist from portal origins |
| Incomplete multipart cleanup | 1-day abort rule |

## Deferred Controls

| Checkov ID | Status | Rationale |
| --- | --- | --- |
| CKV_AWS_21 (versioning) | Disabled | Ephemeral data; versioning would retain deleted uploads and increase cost ([#109](https://github.com/Brad-Edwards/shifter/issues/109)) |
| CKV_AWS_18 (access logging) | Deferred | Unified logging strategy not yet wired for this bucket ([#310](https://github.com/Brad-Edwards/shifter/issues/310)) |
| CKV2_AWS_62 (event notifications) | Not configured | No consumer exists; creating an unused notification stream is an anti-pattern |
| CKV_AWS_144 (cross-region replication) | **Not required** | See evaluation below ([#143](https://github.com/Brad-Edwards/shifter/issues/143)) |

Waivers follow ADR-004-R11: inline `# checkov:skip` on the bucket resource plus
matching `docs/adr/exceptions.yaml` entries. Checkov is blocking in CI
(`platform/terraform/.checkov.yaml`); there is no soft-fail.

## Cross-Region Replication Evaluation (#143)

Issue [#143](https://github.com/Brad-Edwards/shifter/issues/143) (migrated from
PaloAltoNetworks/shifter#219) asks whether CKV_AWS_144 cross-region replication
(CRR) is needed for the portal user-storage bucket.

### Decision: do not implement CRR

CRR remains deferred as an accepted risk for this bucket.

### Evaluation factors

1. **Data class.** Objects are ephemeral user uploads (agent payloads, presigned
   PUT path). The module header states: "No versioning, backup, or storage
   limits. Data is ephemeral." Authoritative application state lives in RDS, not
   S3.

2. **Versioning prerequisite.** S3 CRR requires versioning on the source bucket.
   Versioning is intentionally disabled (CKV_AWS_21 waiver). Enabling CRR would
   force a versioning posture change, increasing storage for every overwrite and
   complicating lifecycle expectations.

3. **Recovery value.** Re-uploading ephemeral files after a regional outage is
   acceptable for demo/workshop readiness. The issue explicitly states the risk
   is "acceptable for now" and "not on critical path for demo readiness."

4. **Operational cost.** CRR requires a destination bucket (second region),
   replication IAM role, cross-region KMS key policy coordination, and ongoing
   replicated storage charges — disproportionate for disposable uploads.

5. **Existing regional resilience.** Portal compute (ASG/EC2), RDS Multi-AZ
   (prod), and other durable tiers have their own HA posture. S3 CRR for uploads
   does not substitute for application-level recovery design.

### Revisit triggers

Re-evaluate CRR when any of the following become true:

- User uploads are promoted from ephemeral to durable/authoritative storage
- Versioning is enabled on this bucket for another control
- A compliance framework mandates geographic redundancy for user object data
- Product requires cross-region read failover for uploaded objects

### If CRR is implemented later

Changes belong in Terraform only:

- `platform/terraform/modules/portal/s3/` — replication configuration,
  versioning toggle, replication role
- Portal env roots — destination region/bucket/KMS inputs via existing tfvars
  overlay conventions

Do not add app-level replication abstractions. Do not broaden portal EC2,
range, or engine-provisioner IAM roles for replication management.

## Anti-Patterns

- Do not enable CRR solely to silence Checkov without a durability requirement.
- Do not bundle portal user-storage waivers with log-archive bucket rationale.
- Do not add repo-wide `skip-check` entries that hide future portal S3 regressions.
