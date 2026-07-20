# Secrets Rotation Strategy Preflight (#159)

Status: pre-implementation guidance

Date: 2026-06-24

Issue: GitHub #159, "Security: Secrets rotation strategy"

This note sets the architecture guardrails for defining and implementing a
production secrets-rotation strategy. It is not an implementation plan or an
operator runbook.

## Scope Boundary

The issue covers production rotation strategy for these credential classes:

- Cognito / OIDC client credentials used by Django login.
- RDS PostgreSQL credentials used by the portal and adjacent workers.
- Django `SECRET_KEY` used for session/signature validation.
- API keys / API tokens used by risk-register and platform APIs.

Keep those as separate credential lifecycles. They share storage and deployment
plumbing, but they do not share rotation semantics.

This work should define a safe strategy and wire the minimum mechanics needed
for production handoff. It should not introduce a new vault abstraction, move
secret material into GitHub Actions, change identity providers, redesign API
auth, or make request-path code fetch cloud secrets directly.

## Baseline Strategy

The implementation should make cadence, automation mode, downtime posture, and
notification ownership explicit for each secret class.

| Secret class | Current incumbent | Baseline cadence | Automation stance | Downtime stance | Notification/audit stance |
| --- | --- | --- | --- | --- | --- |
| RDS portal database credentials | `platform/terraform/modules/portal/rds`, Secret Manager JSON bundle, `entrypoint.sh` hydration into `DB_*` env | 90 days or immediately after suspected exposure / personnel event | Manual scheduled rotation until an alternating-user or IAM DB auth design is implemented; do not claim automatic zero-downtime on the current single-user password shape | Current app reads `DB_PASSWORD` at startup, so a plain password swap needs a coordinated restart. Zero-downtime requires a different DB auth contract, not just a Secret Manager version update | Operator notification via the environment alert channel and deploy/audit evidence; never include password, DSN, or rendered secret JSON |
| Cognito / OIDC client secret | `platform/terraform/modules/portal/cognito`, Cognito app client, Secret Manager JSON bundle, `config._oidc_settings` | 180 days or immediately after suspected exposure | Manual coordinated rotation; preserve old/new client overlap during deploy drain | Existing sessions may survive, but login/session-refresh paths read `OIDC_RP_CLIENT_SECRET` at startup. Rolling deploy must not delete the old app client until old portal instances are drained | Notify operators before and after rotation; audit the app-client id / secret ARN only, not secret material |
| Django `SECRET_KEY` | `aws_secretsmanager_secret.app`, `entrypoint.sh`, `config.settings.SECRET_KEY` | Annual, before production handoff, or immediately after exposure | Manual scheduled rotation unless fallback support is deliberately added | Current settings have no `SECRET_KEY_FALLBACKS`, so rotation invalidates signed sessions/cookies. If no mass logout is acceptable, add explicit fallback-key support first | Notify operators and support because user sessions may be invalidated. Logs/audit may name the rotation event only |
| Platform API tokens | `shared.api_tokens.ApiToken`, `API_TOKEN_MAX_TTL_DAYS`, admin create/revoke audit | Bounded by token expiry, default maximum 365 days; integrations should choose shorter TTLs where feasible | Built-in expiry and audited revocation, not cloud secret rotation | No app restart. Rotation is create replacement token, update client, revoke old token after overlap | Reuse `shared.api_tokens.audit` -> `risk_register.services`; raw token is shown once and never logged |
| Legacy risk-register `X-API-Key` | `risk_register.models.APIKey`, deprecated by PLAT-102 / #1124 | Must have explicit `expires_at`; new integrations should not use it | Expiry/revocation only; do not expand this as the platform token system | No app restart. Prefer migration to `ApiToken` for new work | Reuse existing `AuditLog` paths; do not add a parallel audit table |

## Architecture Decisions

- Use cloud secret managers as the runtime source of secret values: AWS Secrets
  Manager for AWS deployments and GCP Secret Manager for GCP deployments.
  Parameter Store and workflow inputs may carry non-secret references and
  deployment config only.
- Treat the portal's startup secret bundles as process-start inputs. Updating
  the secret manager alone does not update `DB_PASSWORD`, `DJANGO_SECRET_KEY`,
  `FIELD_ENCRYPTION_KEY`, or `OIDC_RP_CLIENT_SECRET` inside already-running
  Django processes.
- Treat RDS zero-downtime rotation as a database-authentication design problem.
  With the current single database user and process-start password, a password
  change can create an outage window. A no-downtime design needs an alternating
  credential/user pattern, RDS Proxy/Secrets Manager rotation with application
  compatibility, or IAM database authentication wired through the Django DB
  connection layer.
- Treat Cognito client-secret rotation as a coordinated identity-client swap,
  not as a generic secret-version bump. Old and new app-client credentials must
  overlap through portal instance drain and session-refresh exposure.
- Treat Django `SECRET_KEY` separately from `FIELD_ENCRYPTION_KEY`, even though
  both live in the app secret JSON bundle today. Rotating
  `FIELD_ENCRYPTION_KEY` can make encrypted model fields unreadable unless a
  separate data re-encryption migration exists.
- Treat API-token rotation as token lifecycle management, not cloud-secret
  rotation. The canonical going-forward principal is `shared.api_tokens.ApiToken`;
  the legacy risk-register `APIKey` remains a compatibility surface only.
- Notifications should use existing operator/audit surfaces. Do not hardcode
  personal email addresses or add a second notification framework for rotation
  events.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #159 |
| --- | --- | --- |
| Runtime secret hydration | `shifter/shifter_platform/entrypoint.sh` and `entrypoint-lib.sh` | Keep provider dispatch and stdin-fed JSON parsing. Do not pass secret JSON or values in argv, Docker env flags, SSM command strings, or workflow logs. |
| Cloud secret adapter | `shared.cloud.get_secrets_store()`, `shared.cloud.aws.secrets`, `shared.cloud.gcp.secrets` | Request-adjacent code and engine services use the provider abstraction. Do not add direct `boto3` / Secret Manager clients in views or API handlers. |
| Startup config validation | `config.settings`, `_env_int`, `_env_bool`, `config._runtime_env.require_environment`, `config/env-manifest.json` | Any new runtime knob or env binding must use the existing settings/parser/manifest pattern and fail loud on invalid config. |
| Settings posture logging | `config._posture.log_settings_posture` | Log non-secret posture only. Rotation status logs may include class, environment, version/stage labels, and reference fingerprints, not values. |
| Secret CMK and IAM boundary | `docs/architecture/secrets-manager-cmk-preflight.md`, portal `aws_kms_key.secrets_manager`, `portal/ec2` IAM policies | Keep KMS decrypt scoped to Secrets Manager and portal-owned secret namespaces. Do not grant unconditioned `kms:Decrypt` or widen key policy casually. |
| Deployment references | `platform/terraform/modules/portal/ssm`, `platform/terraform/modules/portal/ec2/user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`, `_shifter-platform.yml` | SSM parameters and deploy scripts carry secret ARNs/IDs and non-secret config only. Runtime restarts and ASG refreshes reuse existing deploy/drain machinery. |
| RDS credential owner | `platform/terraform/modules/portal/rds` | Keep DB password, DB instance password, and Secret Manager bundle consistent. Do not update one without the other. |
| Cognito credential owner | `platform/terraform/modules/portal/cognito` | Preserve callback/logout URLs, MFA posture, pre-signup Lambda, and secret bundle shape. Do not create a second app-client contract outside the module. |
| API-token lifecycle | `shared/api_tokens/{models,admin,audit,scopes,permissions}.py` | New platform token work uses `ApiToken`, bounded TTLs, audited create/revoke, and central scope validation. |
| Legacy risk-register keys | `risk_register.models.APIKey`, `risk_register.api.authentication`, `risk_register.api.views.APIKeyViewSet` | Keep compatibility explicit. Do not make legacy keys the platform-wide rotation abstraction. |
| Audit logging | `risk_register.models.AuditLog`, `risk_register.services.AuditEvent`, `audit_log`, `audit_log_from_request`, `get_client_ip`, `get_request_id` | Reuse the canonical audit store and trusted source-IP resolver. Do not create a parallel rotation audit table. |
| Log hygiene | `shared.log_sanitize.safe_log_value`, `safe_log_id`, `safe_log_fingerprint`, ECS JSON logging | Logs may identify secret references by fingerprint or suffix only when needed. Never log raw headers, tokens, passwords, or full secret payloads. |
| Error envelopes | `shared.errors.classify_user_message`, DRF auth exceptions, existing bootstrap/status envelopes | Client-facing errors stay fixed/sanitized. Do not return provider exception text or secret references to users. |
| Existing docs | `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md`, `docs/dev/deploy-secrets.md`, `docs/architecture/api-token-authentication-677.md` | Update operator-facing docs once behavior is real. Keep this preflight as the design guardrail, not the runbook. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- **Auth surface:** OIDC login continues through `config._oidc_settings`,
  `config.oidc`, `mozilla_django_oidc`, Django sessions, CSRF middleware, and
  existing provider logout/session-refresh behavior. API programmatic auth
  continues through `shared.api_tokens` first, legacy `risk_register.APIKey`
  only for compatibility, and DRF/session auth as configured in
  `REST_FRAMEWORK`.
- **Secret-handling surface:** secret values live in cloud secret managers,
  Terraform state where existing `random_password` resources already expose
  them, and process memory after startup hydration. They must not appear in
  committed tfvars, local.auto.tfvars examples, workflow YAML, Parameter Store
  String parameters, ConfigMaps, Terraform outputs, GitHub annotations,
  CloudWatch metrics labels, command lines, browser-visible payloads, or docs.
- **Env-binding shape:** startup secret references (`DB_SECRET_ARN`,
  `APP_SECRET_ARN`, `COGNITO_SECRET_ARN`, `REDIS_SECRET_ID`,
  `DC_DOMAIN_PASSWORD_SECRET_ARN`) are non-secret pointers. Resolved values
  (`DB_PASSWORD`, `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`,
  `OIDC_RP_CLIENT_SECRET`, `REDIS_PASSWORD`) are process-local secret values
  and should be materialized only by the existing entrypoint path unless a
  deliberate runtime contract is added.
- **Config validators:** new settings use existing `_env_int`, `_env_bool`,
  list/csv parsing, env manifest generation, and tests. Terraform inputs use
  module variables and validation. Workflow edits must keep fail-loud secret
  selection and pass `actionlint`.
- **OS/process exposure:** deploy and rotation helpers may pass secret ARNs,
  resource names, app-client ids, version labels, and non-secret timing values
  in argv. They must not pass passwords, tokens, `SECRET_KEY`, OIDC client
  secrets, raw API tokens, or rendered JSON bundles in argv, shell traces, SSM
  command bodies, Docker command lines, or process listings.
- **Error envelope:** failed rotations or failed post-rotation validation should
  report the class of secret, environment, affected resource id, and sanitized
  status. Do not surface `ClientError` payloads, DSNs, raw secret references,
  stack traces, or token prefixes beyond existing safe audit conventions.
- **Observability:** capture non-secret rotation evidence: who initiated, class,
  environment, old/new version stage or resource id, deploy/instance-refresh id,
  validation result, and notification result. Successful high-frequency token
  auth must not become per-request audit write amplification.
- **Persistence:** reuse Terraform-managed secrets, RDS/Cognito resources,
  `shared_api_token`, legacy `risk_register_apikey`, and `AuditLog`. Do not add
  durable storage for secret values or rotation transcripts containing values.

Maintainability layers the implementation must build on:

- Existing Terraform modules own cloud resources. Keep DB logic in
  `modules/portal/rds`, Cognito logic in `modules/portal/cognito`, secret
  reference propagation in `modules/portal/ssm` and `modules/portal/ec2`, and
  KMS/IAM policy changes near the consuming module.
- Existing Django settings own runtime config. Do not put runtime parsing in
  random views, management commands, or workflow-only shell snippets.
- Existing cloud adapters own provider-specific reads. Do not duplicate
  Secrets Manager / Secret Manager clients in app modules.
- Existing token models own API-token lifecycle. Do not add a third token table,
  hashing scheme, serializer vocabulary, expiry field, or exception hierarchy.
- Existing audit/logging helpers own rotation observability. Do not create
  app-local audit rows or raw JSON log blobs for this issue.

Extensibility seams:

- **Secret-class policy data:** cadence, owner, automation mode, downtime
  allowance, and notification channel should be represented as class-specific
  policy data or documentation, not hardcoded throughout Terraform, shell, and
  Django.
- **RDS auth method:** the explicit future seam is the DB-authentication mode:
  current password, alternating users, RDS Proxy/managed rotation, or IAM DB
  auth. That choice belongs at the RDS module plus Django database connection
  boundary.
- **Django signing keys:** if session-preserving rotation is required, add a
  `SECRET_KEY_FALLBACKS` env/secret-bundle contract and parse it in
  `config.settings`; keep fallback count/order bounded and documented.
- **OIDC client overlap:** support a current/previous app-client overlap window
  in Terraform/deploy behavior if zero downtime is required. The overlap window
  should be an environment-owned parameter, not an implicit forever-retained
  client.
- **Token TTL:** extend `API_TOKEN_MAX_TTL_DAYS` and central scope/token
  registry behavior, not every app's viewset, when token lifetime policy
  changes.
- **Notification target:** prefer the environment alert topic / `alarm_email`
  seam and `AuditLog` for evidence. A future Slack/PagerDuty integration should
  consume a sanitized rotation event, not direct secret-store payloads.

## Whole-Repo Scope

Likely in scope for the implementation design:

- AWS Terraform:
  `platform/terraform/modules/portal/rds/**`,
  `platform/terraform/modules/portal/cognito/**`,
  `platform/terraform/modules/portal/ec2/**`,
  `platform/terraform/modules/portal/ssm/**`,
  `platform/terraform/modules/portal/redis/**`,
  `platform/terraform/modules/guacamole/**`,
  `platform/terraform/modules/engine-provisioner/**`, and
  `platform/terraform/environments/{dev,proof,prod}/portal/**`.
- GCP parity surfaces if production strategy covers GCP:
  `platform/terraform/gcp/modules/portal/secrets/**`,
  `scripts/gcp/render_runtime_env.py`, and `platform/k8s/gcp/**`.
- Runtime:
  `shifter/shifter_platform/entrypoint.sh`, `entrypoint-lib.sh`,
  `config/settings.py`, `config/_oidc_settings.py`, `config/_runtime_env.py`,
  `config/_posture.py`, and `config/env-manifest.json`.
- Cloud adapters:
  `shifter/shifter_platform/shared/cloud/**` and `engine/secrets.py` only when
  rotation changes provider-neutral secret-read behavior or cache staleness.
- API tokens:
  `shared/api_tokens/**`, `risk_register/models.py`,
  `risk_register/api/authentication.py`, `risk_register/api/views.py`,
  `risk_register/api/serializers.py`, and token/audit tests.
- Deployment:
  `.github/workflows/_shifter-platform.yml`,
  `scripts/portal-deploy/deploy_portal.sh`,
  `scripts/portal_deploy/**`, and ASG instance-refresh/drain behavior if
  rotation requires restarts.
- Documentation:
  `shifter/shifter_platform/documentation/docs/technical/dev/secrets.md`,
  `docs/dev/deploy-secrets.md`, and this preflight note.
- Validation gates:
  `scripts/adr_guard/adr_guard.py --all --level ci`, TFLint for Terraform,
  `actionlint` for workflows, platform `ruff` for Python, import-linter when
  imports change, and Kubernetes validators for manifest changes.

Usually out of scope:

- Replacing Cognito / Identity Platform.
- Rewriting the platform auth model, CTF roles, or OIDC session flow.
- Introducing a generic in-app secret vault service.
- Migrating all runtime secrets to a different provider.
- Rotating field encryption keys without a data migration design.
- Rewriting git history or performing an incident-response secret purge.

## Gotchas And Anti-Patterns

- Do not update only the RDS Secret Manager JSON and call the DB password
  rotated. The actual RDS password and the secret bundle must stay consistent.
- Do not update only the RDS password and leave the secret bundle stale.
- Do not claim RDS zero-downtime rotation while using one database user, a
  process-start `DB_PASSWORD`, and no overlapping credential mechanism.
- Do not assume Secret Manager `AWSCURRENT` updates are picked up by running
  portal processes. Startup secrets are already exported into process env.
- Do not ignore `engine.secrets` cache staleness for per-range secret
  references. Its `SECRET_CACHE_TTL_SECONDS` bounds convergence for secret
  values fetched through that path.
- Do not rotate `FIELD_ENCRYPTION_KEY` as a side effect of rotating Django
  `SECRET_KEY`.
- Do not delete an old Cognito app client before old portal instances and
  session-refresh paths that still use it have drained.
- Do not put rotation commands that include secret values into SSM Run Command,
  GitHub Actions logs, `docker run -e`, shell history, process argv, Terraform
  outputs, or issue comments.
- Do not create a new token model or extend deprecated `risk_register.APIKey`
  as the platform-wide API-token strategy.
- Do not hardcode notification recipients or emit rotation notices containing
  raw secret names when a fingerprint/suffix and environment is enough.
- Do not weaken `.gitleaks`, ADR guard, TFLint, actionlint, kube validators,
  OIDC auth, CSRF, KMS conditions, or deploy fail-loud behavior to make
  rotation easier.

## Non-Goals

- No implementation is performed by this preflight.
- No final production runbook is defined here.
- No live secret is rotated by this change.
- No Terraform state migration, provider replacement, or data re-encryption is
  performed by this issue unless explicitly scoped by the follow-up
  implementation.
- No new cross-cutting exception hierarchy, schema layer, logging format, token
  table, or workflow framework should be introduced for rotation.

## Validation

Architecture, workflow, Terraform, or platform changes on this path must run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Then add stack-native checks for touched surfaces:

```bash
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
cd shifter/shifter_platform && uv run ruff check .
cd shifter/shifter_platform && uv run ruff format --check .
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

Kubernetes changes must also run the repo-required kube-linter and kubeconform
commands.
