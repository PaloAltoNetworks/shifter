# Portal Health Readiness Preflight (#477)

Status: pre-implementation guidance

Date: 2026-06-03

Tracking issue: <https://github.com/Brad-Edwards/Shifter/issues/477>

## Scope Boundary

Issue #477 fixes a false readiness signal: the portal's public `/health`
surface currently returns `200 OK` from `HealthCheckMiddleware` before
`django-health-check` can run its database, cache, and storage probes.

This preflight constrains the upcoming implementation without prescribing
the patch. The shipping behavior must make the traffic-admission health
surface dependency-aware while keeping host-header handling, public response
shape, and provider deployment contracts explicit.

This is requirement-free work. The GitHub issue is the source of truth.
No new Ground Control requirement is attached.

## Architecture Decisions

- `/health` / `/health/` is a readiness surface for routing decisions, not
  a synthetic process-liveness success. It must fail when dependencies
  required to serve user traffic fail.
- `django-health-check` is the incumbent readiness implementation. The
  installed `health_check.db`, `health_check.cache`, and
  `health_check.storage` checks are the canonical baseline probe set. Issue
  #919 deliberately extends that contract with a conditional Channels Redis
  probe when the resolved default channel layer is
  `channels_redis.core.RedisChannelLayer`.
- Host-header accommodation for load-balancer probes is allowed only as a
  narrow admission concern. Middleware may normalize or permit the probe to
  reach the health view, but it must not create the health response, status
  code, or body.
- ALB, Docker, GCP ingress/backend, and Kubernetes readiness probes all
  consume the same semantic contract today. If a separate process-liveness
  endpoint is introduced later, readiness consumers stay on the
  dependency-aware path and liveness consumers move intentionally.
- The public health response stays coarse. It may expose pass/fail status
  and generic check labels, but it must not leak DSNs, bucket names, Redis
  auth URLs, secret IDs, private hostnames, stack traces, or raw exception
  text.
- No new ADR is required for this bug fix. If the implementation introduces
  a new health framework, endpoint taxonomy, observability framework, or
  provider-wide probe abstraction, that crosses into ADR/design-doc work.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #477 |
| --- | --- | --- |
| Health view and checks | `django-health-check`, registered in `config/urls.py` and `INSTALLED_APPS` | Reuse this instead of creating a custom readiness controller or duplicate probe registry. |
| Host-header boundary | `config.middleware.HealthCheckMiddleware`, `DJANGO_ALLOWED_HOSTS`, provider runtime env renderers | Fix the bypass narrowly; do not use `ALLOWED_HOSTS = ["*"]`, broad private CIDRs, or a second host-validation policy. |
| AWS target health | `platform/terraform/modules/portal/alb/main.tf`, `health_check_path` in env tfvars | Preserve the target-group path as a parameter; readiness semantics come from the app, not duplicated Terraform logic. |
| Container health | `shifter/shifter_platform/Dockerfile` `HEALTHCHECK` | Keep Docker health aligned with the documented readiness/liveness choice; avoid a second silent truth source. |
| GCP health consumers | `platform/charts/shifter/templates/web-deployment.yaml`, `portal-backendconfig.yaml`, `values.yaml`, `platform/k8s/gcp/base/web-deployment.yaml` | Any semantic split must be carried through chart values and generated/base manifests together. |
| Backend bundle health contract | `shifter/installation/registry.py` `_PORTAL_HEALTH_CHECK`, `installation.contract.HealthCheck` validators | Public setup/doctor checks continue to target the canonical portal health endpoint. |
| Runtime config parsing | `config.settings` `_env_bool`, `_env_int`, `_env_list`, `_env_csv`; `scripts/gcp/render_runtime_env.py`; EC2 `user_data.sh` | New knobs, if unavoidable, bind through existing env/Terraform/chart surfaces and fail closed on malformed values. |
| Secret hydration | `entrypoint.sh` / `entrypoint-lib.sh` secret-manager flow | Health checks may exercise configured clients but must not move secret values into argv, generated env files, ConfigMaps, logs, or response bodies. |
| Logging and response safety | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `shared.errors` | Log sanitized check failures; return coarse HTTP output without raw exception strings. |
| Architecture enforcement | ADR guard, import-linter, TFLint, actionlint, kube-linter, kubeconform | Probe changes do not weaken repo guardrails or add undocumented exceptions. |

## Cross-Cutting Layers

- Auth surface: `/health` is unauthenticated and internet-reachable through
  the load balancer. It must remain non-sensitive and must not become an
  operator diagnostics API.
- Host validation: `DJANGO_ALLOWED_HOSTS` remains the application host
  allow-list. The load-balancer health-host exception must be path-scoped
  and must still call into the real health view.
- Secret-handling surface: DB, Redis, app, Guacamole, and storage secrets
  are hydrated through `entrypoint.sh` and provider secret managers. Probe
  failure handling must not echo secret IDs, credentials, signed URLs, Redis
  AUTH URLs, or full environment values.
- Env-binding shape: AWS uses Terraform variables, tfvars, SSM/user-data,
  and container env; GCP uses Terraform outputs, `render_runtime_env.py`,
  Helm values/templates, and base manifests. Any new path or toggle belongs
  at these existing seams.
- Config validators: Python changes in `shifter/shifter_platform` must pass
  ruff and import-linter when imports change; Terraform changes must pass
  TFLint; Kubernetes probe changes must pass kube-linter and kubeconform;
  all architecture-touching changes must pass ADR guard.
- OS/runtime exposure: the Docker `HEALTHCHECK`, Kubernetes probes, GCP
  backend health check, AWS ALB target group, and ASG `ELB` health source
  all observe this endpoint. A false positive or false negative here changes
  routing and replacement behavior, not only observability.
- Error-envelope surface: public HTTP output must stay generic. Detailed
  exception data belongs in structured logs using the existing ECS formatter
  and sanitizers.

## Extensibility Seam

The seam is a named health role, not a new probe abstraction:

- Readiness: dependency-aware, consumed by ALB/GCP/backend routing and any
  deployment check that decides whether the portal can serve traffic.
- Liveness: process-up only, optional future endpoint for local container or
  orchestrator restart decisions.

If the implementation adds a liveness endpoint, the path must be
parameterized at the consumer surfaces (`health_check_path`, chart values,
and installation health-check metadata) instead of hard-coded in multiple
files. Until that split exists, `/health` remains readiness.

## Test Contract

Tests for #477 must prove that the health view is reached and the configured
dependency checks are exercised. A test that only asserts status `200` and
body `OK` preserves the defect.

Useful assertions include:

- the old middleware short-circuit cannot satisfy `/health` or `/health/`;
- a failing DB/cache/storage check can make `/health` non-200;
- when Channels resolves to Redis, a failing channel-layer Redis probe can
  make `/health` non-200;
- host-header handling for the load-balancer probe reaches the real health
  view instead of failing early or returning synthetic success;
- public output remains coarse when a dependency raises;
- path behavior is consistent for the ALB path without a trailing slash and
  the Django route with a trailing slash.

## Gotchas

- `config/urls.py` already includes `health_check.urls`; the blocker is the
  early middleware response, not missing URL registration.
- The Docker health check and ALB target group both use the portal health
  path. Changing only one creates two competing definitions of "healthy."
- GCP currently uses `/health/` for pod readiness, pod liveness, and backend
  health. A semantic split must be provider-wide, not AWS-only.
- `django-health-check` may surface implementation-oriented details by
  default. Verify response content under failure before exposing it through
  internet-facing health consumers.
- Database readiness is already a startup gate in `entrypoint.sh`; runtime
  readiness still matters because dependencies can fail after boot.
- Cache readiness means Django cache health and Channels/Redis posture must
  not be conceptually conflated. Since #919, channel-layer Redis readiness is
  a separate conditional probe that is registered only when the resolved
  `CHANNEL_LAYERS` backend is Redis.
- Storage readiness should use the configured storage backend. The current
  `health_check.storage` plugin exercises Django's default storage; do not
  describe it as S3/GCS readiness unless the configured backend and probe
  actually exercise S3/GCS.

## Anti-Patterns

- Returning `HttpResponse("OK")` or any hard-coded success before dependency
  checks run.
- Solving ALB host-header behavior by broadening `ALLOWED_HOSTS` to `*` or
  adding a broad internal-network exception.
- Creating a second readiness endpoint, custom exception hierarchy, custom
  DTO/schema, or custom logging format for this bug.
- Putting raw dependency exception text, DSNs, bucket names, private
  hostnames, secret names, credentials, or stack traces in the public health
  response.
- Treating overload, autoscaling, process liveness, and dependency readiness
  as one binary signal. See `portal-health-scaling-preflight-851.md` for the
  adjacent scaling boundary.
- Weakening ADR guard, import-linter, TFLint, actionlint, kube-linter, or
  kubeconform to land the probe change.

## Non-Goals

- No autoscaling threshold, ASG policy, target-group timing, WAF, or
  stickiness change.
- No runtime swap between Daphne, Gunicorn, Uvicorn, or multiple worker
  models.
- No new metrics framework, Prometheus/statsd/CloudWatch emitter, or
  operator diagnostics surface.
- No change to auth/session/OIDC/Identity Platform behavior.
- No new persistence model, migration, service/repository layer, or shared
  schema.
- No provider migration or backend-bundle redesign.
