# AWS Redis At-Rest Encryption + KMS Preflight (#1059)

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1059>

Source context: #938 enabled AWS ElastiCache AUTH and in-transit encryption,
but deliberately deferred at-rest encryption and a customer-managed KMS key as a
separate control with separate replacement risk.

## Scope Boundary

Issue #1059 closes the replication-group data-at-rest gap for the AWS portal
Redis channel-layer path. The change is infrastructure encryption only:

- enable `at_rest_encryption_enabled = true` on the replicated ElastiCache
  Redis path
- pass a customer-managed KMS key through `kms_key_id`
- remove only the `CKV_AWS_29` / `CKV_AWS_191` replication-group deferrals once
  the controls are actually enabled
- confirm the snapshot/backup posture follows the encrypted replication group

This note is not an implementation plan. The implementation must reuse the
existing AWS portal Terraform roots, the existing `portal/redis` module, the
existing CMK policy conventions, and the ADR-004-R11 Checkov exception
lifecycle.

## Architecture Decisions

- Keep Redis data-at-rest encryption distinct from Redis AUTH/TLS. #938's
  runtime contract, `REDIS_*` environment binding, secret hydration, and
  Django Channels parser are already the right seam and should not change for
  #1059.
- Use a dedicated Redis at-rest CMK. Do not reuse
  `aws_kms_key.secrets_manager`: that key protects Secrets Manager payloads and
  is constrained by Secrets Manager encryption context. Do not reuse the portal
  S3, RDS, CloudWatch logs, messaging, or engine-state CMKs.
- Keep the CMK environment-owned and pass its ARN into
  `platform/terraform/modules/portal/redis/` through an explicit Redis
  at-rest key input. This mirrors the env-root portal CMK pattern already used
  for `aws_kms_key.secrets_manager` and `aws_kms_key.portal_s3` while keeping
  the Redis module as the single owner of ElastiCache resources.
- Treat the replication-group encryption posture as required when
  `enable_replication = true`. The existing single-node path remains the
  documented dev-only/private-subnet plaintext acceptance unless a separate
  issue expands scope.
- Update ADR-004-R11 exception metadata only to match the actual new posture:
  remove the replication-group `CKV_AWS_29` / `CKV_AWS_191` clause, but retain
  unrelated Redis exceptions such as the single-node `CKV_AWS_30` / `CKV_AWS_31`
  acceptance and the Redis AUTH token rotation deferral.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1059 |
| --- | --- | --- |
| Redis resource ownership | `platform/terraform/modules/portal/redis/` | Put `at_rest_encryption_enabled` and `kms_key_id` on the existing replication group; do not create a second cache module. |
| Portal environment roots | `platform/terraform/environments/{dev,proof,prod}/portal/` | Own per-environment CMKs and module wiring here; do not hide the key in tfvars, SSM, or runtime code. |
| CMK conventions | Env-root `aws_kms_key.secrets_manager` / `aws_kms_key.portal_s3`; module CMKs in `portal/rds`, `portal/messaging`, and log modules | Use annual rotation, 30-day deletion window, root/admin statement, service-scoped use, aliases, and normal tags. |
| Checkov policy lifecycle | `platform/terraform/.checkov.yaml`, inline `# checkov:skip`, `docs/adr/exceptions.yaml`, ADR-004-R11 | Remove the two replication-group skips and the matching exception clause only after the controls are enabled. Add no new skip for this work. |
| Redis runtime contract | `docs/architecture/aws-redis-auth-tls-preflight-938.md`, `portal/ssm`, `portal/ec2`, `scripts/portal-deploy`, `entrypoint.sh`, `config/_channels.py` | Leave AUTH/TLS, secret hydration, and Channels behavior unchanged unless a validation failure proves a compatibility issue. |
| Network boundary | Existing SG-reference ingress in `portal/redis` and portal roots | Do not broaden Redis ingress while changing storage encryption. |
| Observability | Existing Redis CloudWatch alarms in `portal/redis` | No new app logs or health payloads are needed for storage encryption posture. |
| Repo validation | `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, Checkov through `_quality.yml` / pre-commit | Keep architecture docs, inline skips, and exception metadata synchronized. |

## Cross-Cutting Layers The Design Must Pass

- Terraform resource policy: the replicated `aws_elasticache_replication_group`
  must set `at_rest_encryption_enabled = true`, keep
  `transit_encryption_enabled = true`, keep `auth_token`, and set `kms_key_id`
  to the Redis data-at-rest CMK. Do not make at-rest encryption depend on
  `enable_redis`; `enable_redis` is runtime wiring, while `enable_replication`
  selects the hardened ElastiCache resource shape.
- Terraform input validation: the Redis module should reject a replicated
  deployment with a blank Redis at-rest KMS key ARN. Keep this separate from
  `secrets_kms_key_arn`, which exists for the Redis AUTH token secret.
- KMS policy gate: the Redis CMK must be service-scoped for ElastiCache use in
  the current account/region and must keep the repo's normal root/admin escape
  hatch, rotation, deletion window, alias, and tags. Runtime EC2/ECS roles do
  not need direct decrypt grants for Redis storage encryption.
- Secret-handling surface: KMS key ARNs and aliases are configuration, not
  secrets. They may appear in Terraform plan output and state. Redis passwords
  remain Secrets Manager values under the existing portal Secrets Manager CMK.
- Env-binding and runtime parsers: no new SSM parameter, `REDIS_URL`,
  `REDIS_PASSWORD`, `REDIS_CA_MODE`, Django settings, entrypoint, deploy script,
  WebSocket auth, health check, DTO, service, repository, or exception-envelope
  change is required by at-rest encryption.
- OS/process exposure: no new secret value is introduced. Do not pass Redis
  passwords, auth-bearing URLs, or secret JSON through argv, user data, systemd,
  workflow logs, or generated env files while touching adjacent Redis code.
- Error and logging surface: failures should surface as Terraform validation,
  Checkov, TFLint, or provider errors. Do not add application logs claiming to
  prove storage encryption, and do not expose key IDs or Redis endpoints in
  browser-facing error payloads.
- Persistence and snapshots: ElastiCache at-rest encryption is provider-owned
  storage encryption. The implementation should verify that automated snapshots
  and backups inherit the encrypted replication group's key and should not add a
  separate snapshot-export bucket/key flow unless the issue scope explicitly
  expands.

## Extensibility Seam

The durable seam is a Redis storage-encryption key input on the Redis module,
for example `redis_at_rest_kms_key_arn`, wired from an environment-owned CMK.
That keeps three concepts separate:

- Redis AUTH token secret encryption: `secrets_kms_key_arn`
- Redis data-at-rest encryption: Redis-specific CMK passed to `kms_key_id`
- Runtime channel-layer selection: `enable_redis` / `CHANNEL_LAYER_BACKEND`

The next likely variation is an externally supplied Redis CMK, a future
environment, or a global/replicated cache posture. Those should be handled by
changing the environment-owned key source or module input value, not by
rewriting Django runtime config or introducing a generic "portal encryption
key" abstraction.

## Gotchas And Anti-Patterns

- Do not reuse `aws_kms_key.secrets_manager` for ElastiCache data at rest. Its
  policy is intentionally scoped to Secrets Manager encryption context.
- Do not remove the entire Redis ADR-004-R11 exception; the single-node
  dev-only plaintext acceptance is separate from the replicated path fixed by
  #1059.
- Do not leave stale `CKV_AWS_29` / `CKV_AWS_191` inline skips after enabling
  the controls, and do not remove them before both attributes are actually set.
- Do not wire only prod and forget `proof`; all portal roots that instantiate
  the shared Redis module must remain coherent.
- Do not introduce `REDIS_URL`, a new Channels settings parser, a new secret
  schema, a new exception hierarchy, or a new cache abstraction for this issue.
- Do not broaden Redis security-group ingress, weaken Checkov, or add
  unconditioned wildcard KMS grants to make the change pass quickly.
- Do not claim Terraform state becomes secret-free; this issue changes storage
  encryption posture, not the existing Terraform-state exposure model.
- Do not hide replacement/downtime risk. Enabling at-rest encryption on an
  existing replication group is replacement-class operational work and the
  implementation PR should make the Terraform plan consequence explicit.

## Non-Goals

- No redesign of Redis AUTH/TLS, Redis AUTH token rotation, Django Channels,
  WebSocket authentication, notification fan-out, health checks, deploy scripts,
  SSM bootstrap, or runtime secret hydration.
- No hardening of the `aws_elasticache_cluster` single-node dev path unless a
  separate issue changes the accepted posture.
- No GCP Redis, Kubernetes, Helm, Docker Compose, RDS, S3, Cognito, Guacamole,
  Network Firewall, or engine-state KMS redesign.
- No cache data migration, legacy snapshot re-encryption, production apply
  sequencing, or PR merge guidance in this preflight.

## Validation Expectations

For the implementation that follows, run the repo-required checks for platform
Terraform and architecture guardrails:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

If the implementation touches workflows, also run `actionlint`. If it touches
runtime Python or shell surfaces despite this boundary, run the relevant
`shifter/shifter_platform` tests and import-linter checks for those surfaces.
