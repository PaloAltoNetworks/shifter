# AWS Portal Redis Channel-Layer Preflight (#849)

Status: implemented (ADR-018). See the landed decision and operating reference
in [`portal-channel-layer-backend.md`](portal-channel-layer-backend.md).

Date: 2026-06-03

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/849>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #849 is the shipping
contract: remove the ambiguity where AWS ElastiCache Redis can be provisioned
while the portal runtime silently uses Django Channels'
`InMemoryChannelLayer`.

Do not implement the issue in this note. The implementation that follows must
reuse the existing AWS portal Terraform, SSM bootstrap, Django Channels config,
and logging contracts rather than adding a parallel cache or websocket
configuration concept.

## Architecture Decisions

- Portal compute placement and channel-layer backend are separate concerns.
  `enable_autoscaling` chooses single EC2 versus ASG capacity. It must not be
  the source of truth for whether Django Channels uses Redis.
- Redis provisioning and Redis runtime wiring should be independent,
  environment-owned knobs. A single-instance dev portal must be able to use
  Redis when Redis is provisioned, and an environment may intentionally disable
  Redis to save cost without changing ASG posture.
- The runtime backend should be explicit in deployed environments. Prefer a
  narrow channel-layer backend enum such as `in_memory` or `redis` over a
  loosely named boolean. If the deployed backend is `redis`, startup must fail
  closed when `REDIS_HOST` is absent rather than falling back to in-memory.
- Preserve the local developer fallback: when no explicit deployed backend is
  set and `REDIS_HOST` is absent, `_build_channel_layers()` may keep returning
  `InMemoryChannelLayer` for tests and local non-container runs.
- Make the actual backend observable from the Django process. Log a single
  non-secret startup posture record derived from the same decision path that
  builds `CHANNEL_LAYERS`, not from Terraform assumptions.
- Do not use this issue to harden AWS ElastiCache auth or TLS. The current AWS
  Redis module has documented Checkov deferrals. If a later issue enables AWS
  Redis AUTH/TLS, follow the existing GCP Redis secret/TLS pattern instead of
  putting auth material in SSM, Docker env literals, logs, or URLs.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #849 |
| --- | --- | --- |
| AWS portal environment roots | `platform/terraform/environments/{dev,prod}/portal/{main.tf,variables.tf,terraform.tfvars}` | Add environment-owned Redis provisioning and channel-layer posture inputs here; keep dev/prod consistent. |
| Redis resource ownership | `platform/terraform/modules/portal/redis/` | Reuse the existing ElastiCache module and SG-reference ingress; do not create a second Redis module or generic cache abstraction. |
| Runtime configuration store | `platform/terraform/modules/portal/ssm/` | Reuse the existing `redis_endpoint` plus `enable_redis` SSM-parameter guard shape. Do not write empty SSM parameters or duplicate a parameter namespace. |
| EC2 and ASG bootstrap | `platform/terraform/modules/portal/ec2/user_data.sh` | Keep SSM read and Docker env hydration centralized here for first boot and ASG refreshes. |
| Single-instance deploy refresh | `.github/workflows/_shifter-platform.yml` | If the SSM-deploy command learns the same Redis posture, update this path too; it mirrors user-data for in-place single-instance deploys. |
| Channels config | `shifter/shifter_platform/config/_channels.py`, `config/settings.py` | Extend the existing pure helper and tests; do not create a second settings module, DTO, or exception hierarchy. |
| Runtime secret hydration | `shifter/shifter_platform/entrypoint.sh` | Secret values belong in Secrets Manager hydration, not in SSM String parameters or Docker command env literals. Endpoint-only AWS Redis config may remain non-secret. |
| Logging | `config.logging.ECSFormatter`, `config._logging_config`, `shared.log_sanitize.safe_log_value()` | Emit ECS JSON logs with backend, host-present, port, and TLS booleans only. Do not log full Redis URLs, AUTH tokens, or raw secret payloads. |
| Local development | `shifter/shifter_platform/docker-compose.yml`, `tests/config/test_channel_layers.py` | Preserve compose Redis and pytest in-memory behavior unless an explicit backend env requests Redis. |
| GCP Redis precedent | `docs/architecture/gcp-redis-auth-tls-preflight.md`, ADR-008-R6 | Reuse the public-config / secret-value / policy-posture split if AWS Redis security posture expands later. |
| Enforcement | `scripts/adr_guard/adr_guard.py`, `.importlinter`, `.tflint.hcl`, `actionlint` | Run the checker for every touched surface; do not weaken guardrails to make the topology switch easier. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: websocket requests still flow through `config/asgi.py`,
  `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and the existing
  consumer/service authorization paths. Redis channel-layer selection is an
  internal fanout backend, not a new user auth boundary or public websocket
  route.
- Secret-handling surface: current AWS Redis endpoint and port are non-secret
  configuration and may flow through SSM String parameters and container env.
  Redis passwords, auth tokens, or full `redis://` / `rediss://` URLs are
  secret-bearing. If introduced later, pass only a secret reference through
  SSM/env and hydrate the value in `entrypoint.sh`, matching DB/app/GCP Redis
  patterns.
- Env-binding shape: `REDIS_HOST`, `REDIS_PORT`, `REDIS_TLS`,
  `REDIS_SECRET_ID`, `REDIS_PASSWORD`, and `REDIS_CA_PEM` already define the
  channel-layer config surface. A new explicit deployed-backend knob belongs at
  this same `_build_channel_layers(env)` seam and must not conflict with
  `REDIS_HOST` presence. The deployed `redis` backend should require
  `REDIS_HOST`; the deployed `in_memory` backend should not accidentally carry
  `REDIS_HOST`.
- Terraform validation surface: module variables and environment roots should
  reject impossible postures at validate/plan time. At minimum, a Redis runtime
  backend must imply a provisioned endpoint, and disabled Redis provisioning
  must not create a non-empty `redis-endpoint` SSM parameter by accident.
- SSM/bootstrap surface: `modules/portal/ssm` owns Parameter Store names and
  `modules/portal/ec2/user_data.sh` owns first-boot Docker env construction.
  The single-instance GitHub Actions SSM deploy block mirrors that env
  construction. Both paths must derive `REDIS_HOST` from the same posture
  contract.
- OS/process exposure: the current Docker `-e REDIS_HOST=...` exposure is
  acceptable only because the endpoint is not a secret. Do not put future Redis
  passwords, AUTH tokens, CA payloads, or full URLs into Docker argv, cloud-init
  logs, generated env files, Terraform comments, or workflow logs.
- Application config surface: `config._channels._build_channel_layers()` is the
  authoritative parser and validator for Channels backend posture. Use
  `django.core.exceptions.ImproperlyConfigured` for invalid runtime config,
  matching the existing TLS/password/CA fail-closed behavior.
- Error-envelope surface: this is startup and infrastructure configuration.
  Failures should surface as Terraform validation errors, SSM/bootstrap
  failures, or Django `ImproperlyConfigured` startup failures. Do not add
  browser-facing websocket error payloads or a new application exception tree
  for this topology ambiguity.
- Logging/observability surface: log the active backend once per Django process
  startup with non-secret posture fields. Useful fields are backend
  (`redis`/`in_memory`), explicit-backend-present, redis-host-present,
  redis-port, redis-tls-enabled, and provider/runtime environment. Avoid the
  raw hostname unless an implementation explicitly accepts internal topology
  disclosure.
- Persistence surface: Redis channel-layer selection should not create a
  database model, migration, repository, or durable audit schema. The posture is
  deploy-time config plus startup observability.

## Whole-Repo View

In-scope repository surfaces for the implementation are:

- `platform/terraform/environments/dev/portal/` and
  `platform/terraform/environments/prod/portal/`
- `platform/terraform/modules/portal/redis/`
- `platform/terraform/modules/portal/ssm/`
- `platform/terraform/modules/portal/ec2/`
- `.github/workflows/_shifter-platform.yml` if single-instance SSM deploy env
  rendering changes
- `shifter/shifter_platform/config/_channels.py` and `config/settings.py`
- `shifter/shifter_platform/entrypoint.sh` only if Redis secrets or TLS are
  introduced
- `shifter/shifter_platform/tests/config/test_channel_layers.py`
- `shifter/shifter_platform/docker-compose.yml` for local Redis behavior
- `docs/architecture/gcp-redis-auth-tls-preflight.md` and ADR-008-R6 as the
  security-posture precedent, not as a mandate to change AWS Redis security in
  this issue

## Extensibility Seam

The durable seam is a small channel-layer runtime posture contract:

- resource posture: whether AWS Redis is provisioned
- runtime backend: `in_memory` or `redis`
- endpoint binding: host and port when the runtime backend is `redis`
- security posture: plaintext private-network Redis today, optional AUTH/TLS
  via the existing secret hydration pattern in a future issue

Keep that seam environment-owned and provider-specific at the Terraform edge,
then map it into the existing Django env contract. The next likely variation is
single-instance dev using Redis for event-like websocket behavior, or an
environment disabling Redis entirely for cost. Neither variation should require
rewriting Django consumers, websocket routes, worker queue logic, or the Redis
module.

## Gotchas And Anti-Patterns

- Do not keep deriving `redis_endpoint` or the SSM `enable_redis` guard from
  `enable_autoscaling`. That is the ambiguity this issue exists to remove.
- Do not create Redis only to leave the portal using in-memory Channels without
  an explicit, logged posture. Provisioned-but-unused Redis can be a deliberate
  maintenance state, but it must not be silent.
- Do not add both `USE_REDIS`, `ENABLE_REDIS`, and backend string settings.
  Pick one explicit runtime posture contract and let `_build_channel_layers()`
  enforce it.
- Do not let a deployed `redis` backend silently degrade to in-memory when the
  SSM parameter is missing, deleted, empty, or not read by user-data.
- Do not treat Redis channel-layer usage as a websocket correctness fix for
  terminal byte streaming. Issue #847 keeps terminal bytes out of Redis.
- Do not copy the GCP `REDIS_SECRET_ID`/TLS path into AWS unless the AWS Redis
  module actually introduces auth/TLS. Endpoint-only AWS plaintext Redis does
  not need secret hydration.
- Do not broaden Redis security-group ingress to compensate for wiring
  complexity. Keep the existing preferred SG-reference pattern.
- Do not log full Redis URLs. A passwordless endpoint is still internal
  topology and a future authenticated URL would be secret-bearing.
- Do not make Terraform outputs, committed tfvars, or workflow variables the
  only source of observability. The running Django process must report the
  backend it actually selected.

## Non-Goals

- No change to Django websocket routing, consumer authorization, CTF domain
  models, worker queue semantics, SQS messaging, database schemas, repositories,
  or service DTOs.
- No AWS ElastiCache AUTH/TLS/encryption hardening in this issue unless a
  separate scoped change accepts the migration and secret-handling work.
- No GCP Redis, Kubernetes, Helm, Docker Compose, or local pytest behavior
  redesign beyond preserving compatibility with the explicit backend contract.
- No new deployment component, Redis proxy, terminal gateway, cache abstraction,
  exception hierarchy, or persistent runtime-posture table.

## Validation Expectations

Run the repo-required checks for touched surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

If the implementation touches Terraform, also run:

```bash
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

If it touches the GitHub Actions single-instance deploy path, run:

```bash
actionlint
```

If it touches Django config or import boundaries, run:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
cd shifter/shifter_platform && uv run pytest tests/config/test_channel_layers.py
```

## Implementation Work Linkage

Landed in one PR for #849 (ADR-018), keeping both ownership slices coherent:

- Terraform posture + wiring: a portal-root `enable_redis` knob (independent of
  `enable_autoscaling`, dev=false / prod=true) drives the `redis-endpoint` SSM
  parameter, the always-written `channel-layer-backend` SSM parameter, the EC2
  `user_data.sh` container env, and the `_shifter-platform.yml` single-instance
  deploy seam.
- Django validation + observability: `config/_channels.py` resolves the explicit
  `CHANNEL_LAYER_BACKEND` contract (fail-closed `redis`, forced `in_memory`,
  legacy-heuristic when unset), and `config/asgi.py` logs the active backend once
  at startup via `log_channel_layer_posture`.

The durable decision and operating guide is
[`portal-channel-layer-backend.md`](portal-channel-layer-backend.md).
