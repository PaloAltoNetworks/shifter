# GCP Redis AUTH/TLS Preflight

Issue: GitHub #963, "[MEDIUM] Redis BASIC tier has no auth or encryption in
transit".

This note records the architecture boundary for hardening the GCP Memorystore
Redis instance. It is not an implementation plan.

## Decision Boundary

The Redis fix is both an infrastructure change and a runtime-contract change.
Upgrading Memorystore to `STANDARD_HA`, enabling AUTH, and requiring server TLS
belongs in `platform-core`; making the portal and workers use the AUTH token
and TLS belongs in the existing GCP runtime render and Django Channels settings
contract.

The implementation must not stop at `google_redis_instance.platform`. A
Terraform-only change would create a secure Redis instance but leave the
application configured with unauthenticated, plaintext `REDIS_HOST` /
`REDIS_PORT` settings.

## Canonical Incumbents

- `platform/terraform/gcp/modules/platform-core/main.tf`: owns the Memorystore
  instance, private service networking, runtime Secret Manager bundles, common
  labels, and workload IAM.
- `platform/terraform/gcp/modules/platform-core/variables.tf`: canonical
  module input validation layer for GCP platform security settings.
- `platform/terraform/gcp/environments/gcp-dev/{variables.tf,main.tf,terraform.tfvars}`:
  environment-owned seam for passing Redis posture into `platform-core`.
- `platform/terraform/gcp/modules/platform-core/outputs.tf` and
  `platform/terraform/gcp/environments/gcp-dev/outputs.tf`: canonical
  Terraform output contract consumed by deployment renderers.
- `scripts/gcp/render_runtime_env.py` and
  `scripts/gcp/tests/test_render_runtime_env.py`: canonical generated runtime
  env contract. It currently emits Redis host/port only.
- `scripts/bootstrap/deploy.py::render_gcp_helm_values`: canonical bridge from
  Terraform outputs and Secret Manager payloads into Helm values and network
  policy private-service CIDRs.
- `platform/charts/shifter/templates/configmap-runtime.yaml` and
  `platform/charts/shifter/templates/networkpolicies.yaml`: canonical runtime
  ConfigMap and private-service egress policy.
- `shifter/shifter_platform/entrypoint.sh`: existing runtime Secret Manager
  hydration path for app, database, OIDC, and Guacamole secrets.
- `shifter/shifter_platform/config/settings.py`: canonical Django Channels
  Redis configuration.
- `shifter/installation/contract.py`: sensitivity/destination precedent:
  secret values must not land in ConfigMaps, generated docs, dry-run output, or
  plan comments.
- `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log`, and
  `shared.cloud.exceptions`: existing logging and cloud-error patterns if
  runtime diagnostics are added.

## Cross-Cutting Layers

Security layers the design must satisfy:

- Terraform resource policy: the Memorystore instance must use
  `tier = "STANDARD_HA"`, `auth_enabled = true`, and
  `transit_encryption_mode = "SERVER_AUTHENTICATION"` at the existing
  `google_redis_instance.platform` boundary. Do not create a second Redis
  module or application-side substitute for provider auth/TLS.
- Terraform input validation: if Redis posture remains configurable, reject
  insecure combinations such as BASIC with auth/TLS enabled or disabled
  auth/TLS in the GCP environment. Prefer a narrow structured posture input or
  validated `redis_tier` / security flags over loosely related booleans.
- Secret handling: the Redis AUTH token is a secret value. Store it in the
  existing Secret Manager runtime bundle pattern, or in an explicitly charted
  Kubernetes Secret if the runtime contract is moved there. Do not put the
  token in `runtimeEnv`, `platform-runtime.generated.env`, Terraform outputs
  intended for ConfigMaps, README examples, logs, or command lines.
- Runtime env-binding: host, port, and TLS mode are configuration and may be in
  `platform-runtime`; the password must be hydrated through
  `entrypoint.sh`/Secret Manager or an equivalent existing secret path before
  Django settings reads it.
- Application config: extend `config/settings.py` at the existing
  `CHANNEL_LAYERS` seam using a `channels_redis` supported host form. Preserve
  local-dev fallback to `InMemoryChannelLayer` when Redis is unset.
- Kubernetes network policy: keep the existing `privateServiceCidrs` flow in
  `render_gcp_helm_values`; it already includes the Redis host as `/32` and
  port `6379`. Do not add broad pod egress to compensate for TLS/auth failures.
- Workload identity and IAM: portal and workers already have
  `roles/secretmanager.secretAccessor`. Do not broaden node, pod, or provisioner
  IAM beyond the minimum needed for existing runtime secret fetches.
- OS/process exposure: use existing argv-array subprocess patterns in bootstrap
  code. Secret payloads must not appear in process argv, shell snippets,
  generated env files, Terraform comments, or `kubectl` dry-run output.
- Error envelopes: Terraform validation/provider errors, bootstrap
  `RuntimeError`/`error(...)`, entrypoint startup failure, and Django settings
  validation are sufficient. Do not add a new application exception hierarchy
  for Redis infrastructure posture.
- Logging/observability: rely on Terraform plan/apply, GCP audit logs,
  Kubernetes rollout health, and existing ECS JSON logs. If startup logs mention
  Redis, log only non-secret posture such as host presence, port, and TLS
  enabled state; never log the AUTH token or full URL.

## Extensibility Seam

The seam is a cache connection contract with three roles:

- public configuration: host, port, and TLS/server-auth mode
- secret value: Redis AUTH token
- policy posture: required tier/auth/TLS validation

Keep that seam role-specific rather than introducing a generic "service
credential" abstraction. The next likely variation is a future GCP production
environment or an auth-token rotation workflow; it should add environment-owned
parameters or a cache secret bundle without rewriting Django domain code,
changing queue/storage/task protocols, or duplicating runtime renderers.

## Gotchas

- Memorystore AUTH/TLS changes are not just mutable flags. Expect replacement,
  endpoint changes, or rollout downtime risk and make the migration explicit in
  the implementation PR.
- Terraform state will contain generated secret material when Terraform wires a
  provider-generated auth string into Secret Manager, matching the existing DB
  password pattern. Do not claim state is secret-free.
- A `rediss://...` URL with a password is a secret value even if it also carries
  host and port. Treat full URLs as secret-bearing unless they are passwordless.
- `platform-runtime.generated.env` is committed today and also rendered into a
  ConfigMap. It is not a place for Redis AUTH.
- The Helm chart has a dedicated Guacamole secret pattern but no generic secret
  env injection for portal/workers today. Reuse or extend existing secret
  handling intentionally; do not hide secret values in `runtimeEnv`.
- The runtime image already fetches DB/app secrets before Django starts. If the
  Redis token is added there, settings tests should prove the hydrated env shape
  drives Channels correctly without affecting local compose defaults.
- TLS for Redis is independent of Cloud SQL TLS, managed ingress TLS, and
  Identity Platform auth. Do not use one of those controls as evidence that
  Redis transport is encrypted.
- Private Service Access and Kubernetes NetworkPolicy reduce reachability but
  are not substitutes for Redis AUTH or TLS.

## Anti-Patterns

- Closing the issue with only `tier = "STANDARD_HA"` and provider auth/TLS
  flags while leaving `channels_redis` unauthenticated.
- Emitting `REDIS_PASSWORD`, `REDIS_URL`, or an auth string through the
  `platform-runtime` ConfigMap or generated env file.
- Creating a parallel Redis settings module, secret fetcher, exception class,
  renderer, or Kubernetes manifest path when the existing runtime env,
  Secret Manager, Helm, and Channels seams cover the need.
- Weakening NetworkPolicies, Workload Identity, Cloud Armor, GKE control-plane
  access, ADR guard, TFLint, or Terraform validation to make rollout easier.
- Collapsing Redis cache/channel-layer concerns into Pub/Sub queue semantics or
  Cloud SQL database connection handling.

## Non-Goals

- Do not redesign channel-layer semantics, notification services, Django cache
  usage, Pub/Sub queues, storage adapters, task runners, DTOs, repositories, or
  service classes.
- Do not migrate AWS ElastiCache, Docker Compose Redis, local development
  defaults, Cloud SQL, Identity Platform, Cloud Armor, or GKE ingress as part of
  this issue unless a compatibility test requires a small guard.
- Do not introduce customer-managed Redis certificates or client mTLS unless a
  separate requirement expands the scope beyond server authentication.
- Do not rotate or migrate cached application data unless the implementation's
  Terraform plan shows Redis replacement and the PR documents the operational
  consequence.

## Validation

Run the repo-required checks for touched surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd platform/terraform && tflint --recursive --config ../../.tflint.hcl
cd platform/terraform/gcp/environments/gcp-dev && terraform init -backend=false && terraform validate
```

If the implementation changes the runtime renderer, chart, entrypoint, or
Django settings, also run the focused renderer/bootstrap/settings tests that
cover Redis env binding and Helm secret placement.

## Outcome — implementation landed 2026-05-11

Landed alongside #959, #960, and #962. End-to-end concrete artifacts:

- `platform/terraform/gcp/modules/platform-core/main.tf` —
  `google_redis_instance.platform` now sets `tier = STANDARD_HA` (via
  `var.redis_tier`), `auth_enabled = true`,
  `transit_encryption_mode = "SERVER_AUTHENTICATION"`. The
  `runtime_secrets` map and `runtime_seeded` secret-version map both
  carry a new `redis` entry whose payload is
  `jsonencode({ password = google_redis_instance.platform.auth_string,
  server_ca_cert = google_redis_instance.platform.server_ca_certs[0].cert })`.
  The CA PEM is delivered alongside the AUTH token because Django Channels
  needs both to verify the Memorystore server certificate; with TLS on,
  `google_redis_instance.platform.port` returns the TLS endpoint (6378),
  which flows through `control_plane_cache.port` → `REDIS_PORT` and is
  reflected in `platform/charts/shifter/templates/networkpolicies.yaml`.
- `platform/terraform/gcp/modules/platform-core/variables.tf` —
  `redis_tier` default is `STANDARD_HA` as the production
  high-availability posture. AUTH and TLS are enforced unconditionally
  on the `google_redis_instance` regardless of tier (both features are
  independent of the tier choice in current GCP), so a future
  disposable environment can override to `BASIC` without weakening the
  security contract. The validation block accepts both
  `BASIC` and `STANDARD_HA` to sanity-check the input.
- `platform/terraform/gcp/modules/platform-core/outputs.tf` —
  `control_plane_cache` now also carries `tls_enabled = true`. The
  Redis secret resource ID flows through the existing
  `runtime_secret_ids` output.
- `scripts/gcp/render_runtime_env.py` — emits `REDIS_TLS=true` and
  `REDIS_SECRET_ID=<runtime_secret_ids["redis"]>` alongside
  `REDIS_HOST` / `REDIS_PORT`. Never emits `REDIS_PASSWORD` or
  `REDIS_URL`; the renderer's structural test asserts the negative.
- `shifter/shifter_platform/entrypoint.sh` — guarded block that, when
  `REDIS_SECRET_ID` is set, hydrates `REDIS_PASSWORD` AND `REDIS_CA_PEM`
  from the Secret Manager payload using the same stdin-fed `python -c`
  shape as the DB password (neither value reaches argv).
- `shifter/shifter_platform/config/settings.py` — extracted
  `_build_channel_layers(env)` helper. Returns `InMemoryChannelLayer`
  with no `REDIS_HOST`; tuple-form for plaintext local dev when TLS is
  off; a `channels_redis` dict-form host (`address` +
  `ssl_cert_reqs="required"` + optional `ssl_ca_data=<PEM>`) when
  `REDIS_TLS=true` + `REDIS_PASSWORD`. The dict-form host is unpacked
  by `channels_redis.utils.create_pool` into
  `aioredis.ConnectionPool.from_url(...)`, so redis-py's SSL kwargs
  flow through and the Memorystore server cert is verified against the
  hydrated CA rather than the system trust store. Raises
  `ImproperlyConfigured` when `REDIS_TLS=true` is set without
  `REDIS_PASSWORD`.
- `shifter/shifter_platform/tests/config/test_channel_layers.py` —
  red-green tests for each branch above (including the negative
  fail-closed branch).
- `scripts/gcp/tests/test_render_runtime_env.py` — extended `_outputs()`
  with `tls_enabled` and a `redis` secret id; added the positive test
  for the new env vars and the negative test that the rendered env
  never carries a password.

- `platform/charts/shifter/templates/networkpolicies.yaml` — egress
  ports for the private-service CIDRs now include 6378 (Memorystore
  TLS endpoint) alongside the existing 6379 (plaintext / AWS path).
  This covers the Helm-based deploy path (`scripts/bootstrap/deploy.py`).
- `platform/k8s/gcp/base/networkpolicies.yaml` — adds a new
  `allow-platform-private-service-egress` policy covering ports 5432,
  6378, and 6379 against RFC1918 destinations. This covers the
  `kubectl apply -k` deploy path that `.github/workflows/_gcp-dev.yml`
  actually executes; without it, the Helm chart's NetworkPolicy would
  not reach the gcp-dev runtime.

ADR-008-R6 (`docs/adr/index.yaml`) is the rule of record; this outcome
section is its implementation evidence. ConfigMap and bootstrap helm
bridge are intentionally unchanged — the existing `runtimeEnv` /
`privateServiceCidrs` flow already carries the new non-secret keys
(`REDIS_TLS`, `REDIS_SECRET_ID`), and AUTH + CA PEM never leave Secret
Manager + the pod's env after hydration.
