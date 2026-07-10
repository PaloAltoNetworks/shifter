# Secrets rotation runbook

Operator procedures for the mechanisms defined in
[`../architecture/secrets-rotation-strategy.md`](../architecture/secrets-rotation-strategy.md).
This file grows as each mechanism ships; it currently covers RDS IAM database
authentication, Django `SECRET_KEY` rotation (issue #159, PR2), automatic Redis
AUTH token rotation (PR3), and Cognito client-secret rotation plus API-token
cadence (PR4).

Apply the architecture guardrails in
[`../architecture/secrets-rotation-strategy-preflight-159.md`](../architecture/secrets-rotation-strategy-preflight-159.md)
before changing production rotation behavior. Never put a secret value in
argv, an SSM command body, a workflow log, a Terraform output, or an issue
comment.

## RDS database credentials: IAM authentication

The running portal (web and workers) authenticates to PostgreSQL with a
short-lived RDS IAM token instead of a stored password, so there is no
database password to rotate for the runtime. The credential is the instance
IAM role plus a dedicated `rds_iam` database user.

Components:

- `mission_control` migration `0041_create_portal_runtime_user` creates the
  `portal_runtime` PostgreSQL role, grants it `rds_iam` and schema-wide DML
  (plus default privileges for future tables). It runs as the master user
  during the normal `migrate` step.
- `platform/terraform/modules/portal/ec2` attaches an `rds-db:connect` IAM
  policy scoped to `portal_runtime` on this instance's RDS resource id.
- `config.db_backends.rds_iam` mints the token per connection
  (`generate_db_auth_token`, a local signing call) and enforces SSL.
- `entrypoint.sh` runs migrations as the master user, then switches the
  long-running process to IAM auth (`DB_IAM_AUTH=true`, `DB_USER=portal_runtime`,
  `DB_PASSWORD` dropped) before exec. The master password user remains the
  schema owner and migrator.

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `DB_IAM_AUTH` | `false` | When `true`, the connection uses the IAM backend. The entrypoint sets it for the AWS runtime; do not set it by hand for `migrate`. |
| `DB_IAM_AUTH_RUNTIME` | `true` | Break-glass switch. Set `false` to keep the runtime on password auth (master user) for a one-off privileged session. |
| `DB_IAM_USER` | `portal_runtime` | The `rds_iam` runtime role. |
| `DB_IAM_REGION` | `AWS_REGION` | Region used to sign the token. |
| `DB_SSLMODE` | `require` | SSL mode for the IAM connection. RDS rejects IAM auth without SSL. |
| `DB_SSL_ROOT_CERT` | unset | Path to the RDS CA bundle. Set together with `DB_SSLMODE=verify-full` to also verify the server certificate. |

### Cutover (per environment)

The cutover is one deploy. Order matters because the IAM policy and the
`portal_runtime` grant must exist before the runtime switches to IAM auth.

1. Confirm the RDS instance has `iam_database_authentication_enabled = true`
   (already set for the portal instance).
2. Deploy the change. In a single deploy: `terraform apply` attaches the
   `rds-db:connect` policy, then the new container runs migrations as the
   master user (creating `portal_runtime` and its grants), then switches the
   runtime connection to IAM auth.
3. Verify: the portal answers `GET /health/`, and the database connection log
   shows the runtime connecting as `portal_runtime`. Confirm no password is
   present in the running process environment
   (`DB_PASSWORD` is unset for the app process).

### Rollback

If the IAM runtime connection fails (for example a missing grant or policy):

1. Set `DB_IAM_AUTH_RUNTIME=false` in the deployment configuration and
   redeploy. The runtime reverts to the master password user, which is
   unchanged.
2. Investigate the grant (`\du portal_runtime` should show `rds_iam`) and the
   `rds-db:connect` policy on the instance role, then re-enable.

No database password rotation is involved in either direction; the master
password credential is untouched by this mechanism.

## Django SECRET_KEY rotation

`SECRET_KEY` signs sessions and cookies. Rotating it with
`SECRET_KEY_FALLBACKS` keeps signatures from the previous key valid through the
rollout, so no user is logged out.

Do **not** rotate `FIELD_ENCRYPTION_KEY` as part of this procedure. It lives in
the same app secret bundle but rotating it makes encrypted model fields
unreadable without a separate re-encryption migration.

The app secret bundle carries an optional `django_secret_key_fallbacks` field
(a JSON array of previous keys). `config.settings` parses it into
`SECRET_KEY_FALLBACKS` (bounded to five keys); the entrypoint hydrates it.

### Procedure

1. Generate a new key:
   `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`.
2. Update the app secret bundle in Secrets Manager: set `django_secret_key` to
   the new key and add the **current** key to the `django_secret_key_fallbacks`
   array.
3. Redeploy so processes hydrate the new values. New signatures use the new
   key; existing sessions signed by the previous key still verify through the
   fallback.
4. After the longest session lifetime has elapsed (so no live session depends
   on the old key), remove the old key from `django_secret_key_fallbacks` and
   redeploy. The fallback list returns to empty in steady state.

Notify operators and support before the rotation: although sessions survive,
the rotation is a security-relevant event worth recording. Audit the rotation
event only, never the key value.

## Redis AUTH token: automatic rotation

The ElastiCache replication-group AUTH token that backs the Django Channels
layer rotates automatically. No routine operator action is required.

Components (`platform/terraform/modules/portal/redis`):

- `rotation.tf` provisions a Secrets Manager rotation Lambda
  (`lambda/redis_rotation.py`), an `aws_secretsmanager_secret_rotation` schedule
  (`redis_auth_rotation_days`, default 90), a VPC security group for the Lambda,
  and scoped IAM.
- The Lambda drives the four-step rotation: generate a new token, apply it to
  ElastiCache with the `ROTATE` strategy (previous token stays valid), verify it
  authenticates over TLS, promote it to `AWSCURRENT`, then trigger a portal ASG
  instance refresh so containers rehydrate `REDIS_PASSWORD`.
- `auth_token` and the secret's `secret_string` are `ignore_changes` in
  Terraform: Terraform bootstraps the initial token; the Lambda owns it
  thereafter. A later `terraform apply` does not revert the rotated token.

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `enable_auth_rotation` | `false` | Enables the rotation Lambda + schedule. The root sets it to `enable_autoscaling`: automatic rotation runs only where the portal is on a refreshable ASG, because ElastiCache `ROTATE` keeps only the two newest tokens, so a consumer that never rehydrates would lose auth at the next rotation. Single-instance deployments use manual rotation instead (below). |
| `redis_auth_rotation_days` | `90` | Rotation interval. |
| `portal_asg_name` | `""` | Portal ASG the Lambda refreshes (`StartInstanceRefresh`) after promoting the new token. The root wires it to `module.ec2.asg_name` whenever `enable_auth_rotation` is on. |

### Manual / forced rotation

Trigger an immediate rotation with
`aws secretsmanager rotate-secret --secret-id shifter-<env>-redis-auth`. Watch
the Lambda's CloudWatch log group `/aws/lambda/<name_prefix>-redis-rotation`;
the secret value never appears in the logs.

### Failure handling

Secrets Manager retries a failed rotation and surfaces it on the secret. If the
Lambda cannot reach Redis (the `testSecret` step) or the ElastiCache modify
fails, the new token is not promoted and the previous token remains in use, so
the Channels layer keeps working. Investigate the Lambda log group, then let
the next scheduled attempt proceed or force one with `rotate-secret`.

## Cognito client secret: operator-triggered rotation

Cognito has no API to rotate an app client's secret in place, so rotation is a
blue/green client replacement run on demand by an operator. It is **not**
scheduled: a scheduled EventBridge reminder emails the admin when rotation is
due (default 180 days, `cognito_rotation_reminder_days`, published to the portal
alerts SNS topic).

Components (`platform/terraform/modules/portal/cognito`):

- `rotation.tf` provisions an on-demand rotation Lambda (`lambda/cognito_rotation.py`)
  with scoped IAM, plus the EventBridge Scheduler reminder + its SNS-publish role.
- The Lambda describes the current app client, creates a new one copying its
  config, writes the new `client_id` / `client_secret` into the OIDC bundle,
  and refreshes the portal ASG so containers rehydrate the new client. The
  previous client is left in place.
- The OIDC secret bundle's `secret_string` is `ignore_changes` in Terraform:
  Terraform bootstraps the initial client; the Lambda owns the bundle after.

### Procedure

1. Run the rotation: `aws lambda invoke --function-name <name_prefix>-cognito-rotation /dev/stdout`.
   The response reports `new_client_id` and `previous_client_id`; the secret
   value never appears in the output or logs.
2. The Lambda triggers an ASG instance refresh; wait for it to complete so all
   portal instances are serving with the new client.
3. Confirm login works against the new client. The previous client stays valid
   during this window, so in-flight sessions are unaffected.
4. After the refresh has drained in, retire the previous client:
   `aws cognito-idp delete-user-pool-client --user-pool-id <pool> --client-id <previous_client_id>`.
   Do **not** delete the Terraform-managed bootstrap client while it is the
   active one.
5. Reconcile Terraform: a later `terraform apply` leaves the bundle untouched
   (`ignore_changes`); the Terraform-managed client remains defined but unused.
   Audit the app-client id only, never the secret.

## API tokens and legacy API keys: cadence

Platform API tokens (`shared.api_tokens.ApiToken`) are not cloud-secret
rotations; they expire and are revoked. Issue them with a bounded TTL
(`API_TOKEN_MAX_TTL_DAYS`, default 365; integrations should choose shorter),
and rotate by issuing a replacement, updating the client, and revoking the old
token after overlap. Create/revoke are audited via `shared.api_tokens` →
`AuditLog`; the raw token is shown once and never logged.

The legacy `risk_register.APIKey` is a compatibility surface only: every key
must carry an explicit `expires_at`, and new integrations use `ApiToken`.
