# Secrets rotation strategy

Status: accepted strategy (implementation tracked in #159)

Issue: GitHub #159, "Security: Secrets rotation strategy"

This document defines the production rotation strategy for Shifter's
long-lived credentials. It answers *what* the rotation policy is for each
credential class; the architecture guardrails live in
[`secrets-rotation-strategy-preflight-159.md`](secrets-rotation-strategy-preflight-159.md)
and the per-mechanism operator runbooks ship with the PR that implements each
mechanism (see [Delivery](#delivery)). High-level operator notes are in
[`technical/dev/secrets.md`](../../shifter/shifter_platform/documentation/docs/technical/dev/secrets.md#rotating-secrets).

## Scope

Production rotation for these credential classes:

- **RDS PostgreSQL credentials**: portal and adjacent worker database access.
- **Cognito / OIDC client secret**: Django login.
- **Django `SECRET_KEY`**: session and signature validation.
- **Redis AUTH token**: the ElastiCache replication group backing the Django
  Channels layer.
- **Platform API tokens** (`shared.api_tokens.ApiToken`) and the legacy
  `risk_register.APIKey` compatibility surface.

Scenario and range-infrastructure secrets are **out of scope**: the DC domain
(Active Directory Administrator) password and the NGFW SSH key are range
scenario content, not platform production credentials. They are covered by the
documented-manual approach in ADR-004-R11 exception #757, and the DC password
in particular must stay constant for scenario reproducibility.

Each class is a separate lifecycle. They share storage (cloud secret managers)
and deployment plumbing, but they do not share rotation semantics. The
`FIELD_ENCRYPTION_KEY` is explicitly **out of scope**: it lives in the same app
secret bundle as `SECRET_KEY` but rotating it requires a data re-encryption
migration, which this work does not perform.

Out of scope (per preflight): a new in-app vault abstraction, moving secret
material into GitHub Actions, changing identity providers, redesigning API
auth, or making request-path code fetch cloud secrets directly.

## Questions answered

The issue poses four questions. The platform-wide answers:

1. **How often should each secret rotate?** Per-class cadence in the
   [policy table](#policy). Cadences are calendar baselines; any suspected
   exposure or personnel event triggers immediate rotation regardless of
   schedule.
2. **Automatic vs manual?** Mixed, by class. The Redis AUTH token (no
   session/identity coupling) moves to AWS Secrets Manager automatic rotation.
   Identity- and session-coupled secrets (Cognito client secret, Django
   `SECRET_KEY`) use coordinated rotation because automatic rotation cannot
   satisfy their drain/overlap requirements under the current startup-hydration
   runtime. RDS removes the rotating credential entirely by moving to IAM
   database authentication.
3. **How to handle rotation without downtime?** The portal hydrates secret
   values into process environment **once at startup**; updating a secret
   version does not affect running processes. Zero-downtime therefore depends
   on the credential's auth contract, not on a Secret Manager version bump:
   - RDS: IAM database authentication mints a short-lived token per
     connection, so there is no password to swap (see
     [RDS](#rds-postgresql-credentials)).
   - `SECRET_KEY`: `SECRET_KEY_FALLBACKS` keeps signatures from the previous
     key valid across the rollout, so sessions survive.
   - Cognito: an old/new app-client overlap window keeps logins working until
     old portal instances drain.
   - Redis AUTH: the rotation Lambda applies the new token with the ElastiCache
     `ROTATE` strategy (previous token stays valid), then refreshes the portal
     ASG so containers rehydrate it; no Channels-layer interruption.
4. **Who is notified?** The environment alert channel (`alarm_email` SNS topic)
   for operator notification and `risk_register.AuditLog` for durable evidence.
   Notifications and audit records carry the secret **class, environment, and a
   reference fingerprint** only, never the value, DSN, ARN payload, or token
   prefix. No personal recipients are hardcoded.

## Policy

| Secret class | Cadence (baseline) | Automation mode | Downtime posture | Notification / audit |
| --- | --- | --- | --- | --- |
| RDS portal DB credentials | N/A (no stored password under IAM auth; the IAM principal is the credential) | IAM database authentication (per-connection token); no secret rotation | Zero-downtime: token minted per connection, SSL enforced | Audit the principal/policy change only; alert on auth-failure spikes |
| Cognito / OIDC client secret | 180 days, or immediately on exposure | Operator-triggered blue/green rotation (on-demand Lambda creates a new app client; no in-place secret-rotation API) + scheduled email reminder | New client created and bundle swapped; old client overlaps through ASG drain; no delete-before-drain | Reminder email on cadence; audit app-client id / secret ARN, not the value |
| Django `SECRET_KEY` | Annual, before production handoff, or on exposure | Coordinated rotation with `SECRET_KEY_FALLBACKS` | Zero-downtime via fallback keys; bounded fallback list | Notify operators (sessions may revalidate); audit the rotation event only |
| Platform API tokens (`ApiToken`) | Bounded by token TTL; default max 365 days, integrations choose shorter | Built-in expiry + audited revoke; not cloud-secret rotation | No restart: issue replacement, swap client, revoke old after overlap | Reuse `shared.api_tokens` audit → `AuditLog`; raw token shown once, never logged |
| Legacy `risk_register.APIKey` | Must set explicit `expires_at`; not for new integrations | Expiry / revocation only | No restart; migrate new work to `ApiToken` | Reuse existing `AuditLog`; no parallel audit table |
| Redis AUTH token | 90 days, or on exposure | AWS Secrets Manager automatic rotation (custom Lambda, ElastiCache `ROTATE`) | Previous token stays valid; ASG instance refresh rehydrates consumers | Alert on rotation result; audit the version stage transition |

## Per-class strategy

### RDS PostgreSQL credentials

**Decision:** move portal and worker database access to **IAM database
authentication**, on by default in the deploy path. This removes the stored DB
password from the rotation problem entirely: the credential becomes the IAM
principal, and each connection presents a short-lived (15-minute) signed token.

Rationale: the portal reads `DB_PASSWORD` once at startup, so a plain password
swap requires a coordinated restart and creates an outage window for the single
database user. IAM auth converts the problem from "rotate a shared password" to
"manage an IAM policy," which is auditable, has no value to leak into logs or
state, and is zero-downtime because the token is minted per connection.

Target mechanism (PR2): Django's connection layer mints the token via
`generate_db_auth_token` (a local SigV4 signing operation, no network call) and
connects with `sslmode` enforced against the RDS CA bundle; an `rds-db:connect`
IAM policy scoped to the portal role and the IAM-mapped database user; the
database user granted `rds_iam`. `iam_database_authentication_enabled` is
already true on the portal RDS instance. The cutover and rollback runbook ships
with PR2.

### Cognito / OIDC client secret

**Decision:** coordinated app-client credential swap with an old/new overlap
window, not a generic secret-version bump.

Rationale: login and session-refresh paths read `OIDC_RP_CLIENT_SECRET` at
startup. A rotation that deletes the old app client before old portal instances
drain breaks in-flight logins. Keeping both credentials valid through the
deploy drain preserves availability. The overlap window is an
environment-owned parameter, not an implicitly forever-retained client.

### Django `SECRET_KEY`

**Decision:** coordinated rotation backed by `SECRET_KEY_FALLBACKS`.

Rationale: `SECRET_KEY` signs sessions and cookies. Rotating it without
fallback support invalidates every signed session (mass logout). Adding a
bounded `SECRET_KEY_FALLBACKS` list lets the new key sign while the previous
key still validates, so the rollout is zero-downtime. `FIELD_ENCRYPTION_KEY`
is **not** rotated alongside `SECRET_KEY`; doing so would make encrypted model
fields unreadable without a separate re-encryption migration. The fallback
contract ships with PR2.

### Platform API tokens and legacy keys

**Decision:** API-token rotation is token-lifecycle management, not
cloud-secret rotation. `shared.api_tokens.ApiToken` is the canonical
going-forward principal: bounded TTLs (`API_TOKEN_MAX_TTL_DAYS`), audited
create/revoke, central scope validation. Rotation is "issue replacement →
update client → revoke old after overlap"; no app restart. The legacy
`risk_register.APIKey` remains a compatibility surface only. It must carry an
explicit `expires_at`, and new integrations use `ApiToken`. Cadence guidance
ships with PR3.

## Notification and audit

Rotation events use existing operator and audit surfaces:

- **Operator notification:** the environment alert SNS topic (`alarm_email`
  seam). A future Slack/PagerDuty integration consumes a sanitized rotation
  event, not a secret-store payload.
- **Evidence:** `risk_register.AuditLog` via the canonical
  `shared.api_tokens` / `risk_register.services` audit paths. No parallel
  rotation audit table.

Every notification and audit record identifies the secret by **class,
environment, and reference fingerprint/suffix** only. Raw passwords, tokens,
`SECRET_KEY`, OIDC client secrets, DSNs, rendered secret JSON, and full ARNs
never appear in notifications, logs, SSM command bodies, process argv,
Terraform outputs, or issue comments.

## Delivery

Delivered incrementally on `159-secrets-rotation`:

1. **PR1 (this document)**: the strategy.
2. **PR2**: RDS IAM database authentication (Django connection layer +
   Terraform IAM/grant) and Django `SECRET_KEY_FALLBACKS`, with the RDS cutover
   and rollback and `SECRET_KEY` rotation runbooks.
3. **PR3**: the Redis AUTH automatic-rotation Lambda (ElastiCache `ROTATE` +
   ASG-refresh finalize), with its runbook; the #757 exception narrowed to drop
   Redis.
4. **PR4**: Cognito client-secret rotation (operator-triggered blue/green
   Lambda + scheduled email reminder) and API-token cadence guidance. Closes the
   issue.

Operator runbooks for each mechanism land with the implementing PR, once the
behavior is real.

## References

- [`secrets-rotation-strategy-preflight-159.md`](secrets-rotation-strategy-preflight-159.md):
  binding architecture guardrails.
- [`../dev/secrets-rotation-runbook.md`](../dev/secrets-rotation-runbook.md):
  operator procedures for each shipped mechanism.
- [`technical/dev/secrets.md`](../../shifter/shifter_platform/documentation/docs/technical/dev/secrets.md):
  secret inventory and high-level operator notes.
- [`../dev/deploy-secrets.md`](../dev/deploy-secrets.md): deploy-time secret
  configuration.
- [`secrets-manager-cmk-preflight.md`](secrets-manager-cmk-preflight.md): KMS
  CMK and IAM boundary for Secrets Manager.
- [`api-token-authentication-677.md`](api-token-authentication-677.md):
  platform API-token lifecycle.
