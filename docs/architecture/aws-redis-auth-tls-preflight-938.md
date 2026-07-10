# AWS Redis AUTH/TLS Preflight (#938)

Status: pre-implementation guidance

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/938>

## Scope Boundary

Issue #938 hardens the AWS ElastiCache Redis path used by Django Channels.
The shipping contract is the GitHub issue: AWS Redis must require AUTH and use
in-transit encryption, or any deliberately retained plaintext posture must be
documented in the module with a threat-model rationale.

This note is not an implementation plan. The implementation must reuse the
existing AWS portal Terraform modules, SSM bootstrap paths, runtime secret
hydration, Django Channels configuration, health-check registry, and logging
contracts.

## Architecture Decisions

- Treat Redis transport and Redis authentication as part of one runtime
  contract. A Terraform-only change that enables ElastiCache TLS/AUTH without
  wiring the portal and workers to `REDIS_TLS` and a hydrated password is not a
  valid fix.
- Reuse the existing channel-layer environment contract:
  `CHANNEL_LAYER_BACKEND`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_TLS`,
  `REDIS_SECRET_ID`, `REDIS_PASSWORD`, and `REDIS_CA_PEM`. Do not create a
  second Redis settings module, URL parser, secret fetcher, or backend flag.
- Secret values belong in AWS Secrets Manager under the portal Secrets Manager
  CMK. SSM may carry only non-secret configuration and secret references, such
  as a Redis secret ARN or ID.
- The active Django process must continue to choose the backend through
  `config._channels._build_channel_layers()` and log only the existing
  non-secret posture fields. Do not log Redis hostnames, AUTH tokens, full
  `rediss://` URLs, or CA PEM material.
- Reuse the #919 readiness behavior. Redis readiness is already a conditional
  `django-health-check` plugin registered when `CHANNEL_LAYERS` resolves to
  `channels_redis.core.RedisChannelLayer`; do not create a separate Redis
  readiness endpoint or duplicate probe registry.
- Keep AWS Redis hardening distinct from at-rest encryption and CMK hardening.
  If the implementation enables only AUTH and transit encryption, do not remove
  at-rest/CMK Checkov deferrals or exception text as if #938 solved them. If it
  also enables at-rest encryption, update the module skips and ADR exception
  registry to match the actual new posture.
- The single-node `aws_elasticache_cluster` path must not remain an ambiguous
  production-like plaintext path. Either harden it through the same runtime
  contract, replace it with a hardened replication-group shape, or document the
  retained plaintext posture in the module as dev-only/private-subnet
  acceptance with rationale.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #938 |
| --- | --- | --- |
| Redis resource ownership | `platform/terraform/modules/portal/redis/` | Add TLS/AUTH posture here; do not create a parallel cache module. |
| AWS environment roots | `platform/terraform/environments/{dev,prod}/portal/` | Own per-environment posture, secret wiring, and operational rollout consequences here. |
| Secret storage | Existing portal Secrets Manager CMK and secret patterns in the portal roots and modules | Store Redis AUTH material as a Secrets Manager secret encrypted by the portal CMK; do not commit or output raw token material. |
| Runtime config store | `platform/terraform/modules/portal/ssm/` | Publish non-secret Redis connection config and secret references through the existing SSM namespace. |
| First boot | `platform/terraform/modules/portal/ec2/user_data.sh` | Read the same SSM keys and pass only non-secret env or secret references into `docker run`. |
| In-place deploy | `scripts/portal-deploy/deploy_portal.sh` | Mirror first-boot env hydration using argv arrays; do not leave single-instance redeploy on a plaintext shape. |
| Runtime secret hydration | `shifter/shifter_platform/entrypoint.sh` and `entrypoint-lib.sh` | Reuse `fetch_runtime_secret`; parse Redis secret payloads from stdin-fed Python so secret values do not appear in process argv. |
| Channels config | `shifter/shifter_platform/config/_channels.py` and `tests/config/test_channel_layers.py` | Extend the existing pure helper/tests only if AWS trust handling needs a small provider-neutral seam. |
| Readiness | `shifter/shifter_platform/config/health.py`, `config/health_checks.py`, and `tests/mission_control/test_health.py` | Preserve the conditional channel-layer Redis probe and coarse public health response. |
| Logging hygiene | `config._logging_config`, `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()` | Keep diagnostics non-secret; never log the Redis password, CA, full URL, or env dump. |
| Architecture enforcement | `scripts/adr_guard/adr_guard.py`, `.tflint.hcl`, `actionlint`, `.importlinter` | Keep ADR exceptions and inline skips synchronized with the actual security posture. |
| GCP precedent | `docs/architecture/gcp-redis-auth-tls-preflight.md`, ADR-008-R6 | Reuse the public-config / secret-value / policy-posture split; do not blindly copy GCP's private-CA assumption into AWS. |

## Cross-Cutting Layers The Design Must Pass

- Terraform resource policy: the ElastiCache path selected for deployed Redis
  must set in-transit encryption and an AUTH token together. Provider token
  constraints, update strategy, and replacement/downtime behavior must be
  encoded in Terraform rather than left as operator folklore.
- Terraform validation: environment and module inputs must reject impossible
  combinations, such as `CHANNEL_LAYER_BACKEND=redis` without an endpoint,
  `REDIS_TLS=true` without a secret reference/password path, or a production
  replication-group path that keeps plaintext without an explicit documented
  acceptance.
- Secret-handling surface: Redis AUTH material is a secret value. It must not
  appear in tfvars, SSM String parameter values, Terraform outputs intended for
  humans, generated env files, cloud-init logs, Docker command literals, GitHub
  workflow logs, or a full `rediss://` URL outside process memory. Terraform
  state will still contain generated secret material if Terraform creates the
  token or secret version; do not claim otherwise.
- IAM and KMS: the portal EC2 role's Secrets Manager read allow-list must cover
  the Redis secret, and the existing portal CMK decrypt policy must still satisfy
  ADR-004-R10. Do not broaden to wildcard Secrets Manager or unconditioned
  wildcard `kms:Decrypt` to make the new secret readable.
- SSM/bootstrap: `portal/ssm` owns Parameter Store names. `user_data.sh` and
  `scripts/portal-deploy/deploy_portal.sh` must read the same keys and emit the
  same env shape. A secure first boot with an insecure redeploy path is a
  regression.
- OS/process exposure: passing a Redis secret reference to `docker run -e` is
  acceptable by the existing DB/app-secret pattern; passing `REDIS_PASSWORD`,
  an auth-bearing URL, or CA PEM through Docker argv is not. The token may become
  process environment after `entrypoint.sh` hydration, matching the current
  DB password model, but must not be present in shell history, cloud-init output,
  systemd unit files, or launch-template/user-data literals.
- Runtime env binding: `config._channels` is the canonical parser. If AWS can
  rely on a system trust store while GCP requires `REDIS_CA_PEM`, make that
  distinction explicit and tested at this seam. Do not silently weaken the GCP
  fail-closed `REDIS_CA_PEM` behavior to make AWS pass.
- Auth surface: WebSocket authentication remains `AllowedHostsOriginValidator`,
  `AuthMiddlewareStack`, and the existing consumer/service authorization paths.
  Redis AUTH is backend-to-backend transport protection, not a user auth or
  session authorization substitute.
- Error-envelope surface: invalid Redis posture should fail as Terraform
  validation/provider errors, SSM/bootstrap failures, entrypoint startup
  failures, or Django `ImproperlyConfigured`. Do not add browser-facing
  websocket payloads or a new application exception hierarchy for Redis
  infrastructure wiring.
- Readiness surface: `/health` must keep returning coarse labels only. A Redis
  TLS/AUTH failure may make the Redis channel-layer probe fail readiness, but
  the public response must not leak endpoints, auth URLs, secret IDs, or raw
  exception strings.

## Extensibility Seam

The durable seam is the Redis connection posture split:

- public configuration: host, port, backend posture, and TLS enabled
- secret value: Redis AUTH token in a provider secret manager
- trust material: CA PEM when required, or an explicit tested trust mode when a
  provider uses the system trust store
- policy posture: Terraform validation and documented acceptance for any
  intentionally plaintext path

Keep that seam provider-aware at the Terraform/bootstrap edge and
provider-neutral at the Django Channels helper. The next likely changes are
Redis auth-token rotation and a future decision on at-rest encryption/CMK; those
should add parameters at the Redis module/runtime-secret seam, not rewrite
websocket consumers, health views, or notification/domain services.

## Gotchas And Anti-Patterns

- Do not assume the existing GCP TLS path is directly reusable without deciding
  what AWS does for CA verification. Today `_build_redis_layer()` requires
  `REDIS_CA_PEM` whenever `REDIS_TLS=true`; changing that must preserve GCP's
  private-CA fail-closed behavior.
- Do not hard-code GCP's TLS port. AWS ElastiCache and GCP Memorystore may have
  different port behavior; consume the Terraform output/env `REDIS_PORT`.
- Do not use `REDIS_URL` as a shortcut. Full Redis URLs become secret-bearing
  as soon as they contain a password and are easy to leak through logs/tests.
- Do not pass `REDIS_PASSWORD` from SSM directly into `docker run`. Use a secret
  reference plus `entrypoint.sh`.
- Do not broaden Redis security-group ingress while adding TLS/AUTH. The
  existing preferred source-SG ingress pattern still applies.
- Do not conflate Redis AUTH/TLS with Django session auth, ALB TLS, RDS TLS,
  Cognito/OIDC, or Network Firewall inspection. Those controls do not encrypt or
  authenticate the Redis channel-layer connection.
- Do not close the issue by documenting plaintext as accepted unless the module
  names the posture, rationale, scope, owner, and expiry/review trigger.
- Do not remove ADR-004-R11 exceptions or Checkov skips before the corresponding
  control is actually enabled.

## Non-Goals

- No redesign of Django Channels semantics, websocket routes, consumer
  authorization, CTF/session models, notification fan-out, SQS worker queues,
  repositories, DTOs, or domain services.
- No new Redis proxy, cache abstraction, service credential abstraction,
  custom exception hierarchy, metrics framework, or operator diagnostics API.
- No GCP Redis, Kubernetes, Helm, Docker Compose, local pytest, Cloud SQL/RDS,
  Cognito/OIDC, Guacamole, or Network Firewall redesign except for small
  compatibility guards needed to preserve the shared Redis env contract.
- No promise that Terraform state becomes secret-free.
- No merge or production apply guidance; rollout sequencing belongs in the
  implementation PR once the Terraform plan is concrete.

## Validation Expectations

Run the repo-required checks for touched architecture and platform surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

If runtime config changes, also run:

```bash
cd shifter/shifter_platform && uv run pytest tests/config/test_channel_layers.py tests/mission_control/test_health.py
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
```

If GitHub Actions or SSM redeploy wiring changes, also run:

```bash
actionlint
```
