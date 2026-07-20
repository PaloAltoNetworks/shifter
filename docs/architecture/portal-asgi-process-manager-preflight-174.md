# Portal ASGI Process Manager Preflight (#174)

Status: pre-implementation guidance

Date: 2026-06-03

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/174>

## Scope Boundary

Issue #174 switches the production portal web process from the current single
Daphne process to a Gunicorn-managed ASGI process pool using Uvicorn workers.
The change is a runtime/process-manager hardening change, not an application
routing, websocket protocol, deployment-topology, auth, or channel-layer
redesign.

The GitHub issue is the source of truth. There is no Ground Control
requirement for this run.

## Architecture Decisions

- Keep `config.asgi:application` as the single ASGI application contract for
  HTTP and websocket traffic. Gunicorn/Uvicorn is only the server/process
  manager around that application.
- Preserve the existing portal container entrypoint as the canonical runtime
  bootstrap. It hydrates secrets, waits for the database, runs migrations,
  compiles messages, collects static assets, then execs the long-running web
  process.
- Keep all deploy targets on one default web command by changing the image
  default. AWS Docker runs, GCP chart/Kustomize web deployments, and local
  Docker Compose all consume the same image entrypoint unless an explicit
  command override is provided.
- Make the worker-count policy environment-owned. A fixed issue example of
  four workers is acceptable as a default, but the obvious production seam is
  an env knob such as `PORTAL_WEB_WORKERS` / `WEB_CONCURRENCY`, bounded and
  documented, so AWS instance size and GCP pod limits can tune the process pool
  without rebuilding the image.
- Treat the `uvicorn.workers.UvicornWorker` string in the migrated issue as a
  compatibility detail, not a new architecture boundary. Current Uvicorn docs
  mark `uvicorn.workers` deprecated and recommend the separate
  `uvicorn-worker` package
  (<https://www.uvicorn.org/deployment/#gunicorn>). The implementation should
  either use the supported worker package while preserving the "Gunicorn with
  Uvicorn workers" contract, or deliberately pin and test the deprecated import
  path.
- Do not remove Daphne from dependencies or `INSTALLED_APPS` unless the same
  change updates and tests the local `runserver` / Channels development
  contract. The acceptance criterion is to stop using Daphne as the production
  process manager, not necessarily to erase every Daphne reference.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #174 |
| --- | --- | --- |
| ASGI routing and websocket auth | `shifter/shifter_platform/config/asgi.py` | Preserve `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and combined Mission Control + experiment websocket routing. |
| Channels/Redis env binding | `config/_channels.py`, `config/settings.py`, `entrypoint.sh`, `scripts/gcp/render_runtime_env.py` | Reuse the existing `CHANNEL_LAYERS` helper and fail-closed Redis TLS/AUTH posture; do not create a server-specific Redis config. |
| Runtime bootstrap | `shifter/shifter_platform/entrypoint.sh` and `entrypoint-lib.sh` | Keep secret hydration and Django setup before the final `exec`; do not bypass it in Kubernetes, AWS user data, or Compose. |
| Dependency lock and image install | `shifter/shifter_platform/pyproject.toml`, `uv.lock`, `Dockerfile` | Add any Uvicorn worker dependency through the locked `uv` workflow and copy only console scripts the final command actually invokes. |
| Portal deployment paths | AWS `platform/terraform/modules/portal/ec2/user_data.sh`, `.github/workflows/_shifter-platform.yml`, GCP `platform/k8s/gcp/base/web-deployment.yaml`, Helm `platform/charts/shifter/templates/web-deployment.yaml` | The default image command should work unchanged for all web deployments; command overrides stay reserved for workers and schedulers. |
| Health checks | `config.middleware.HealthCheckMiddleware`, Docker `HEALTHCHECK`, AWS ALB health check path, GCP readiness/liveness probes, GCP BackendConfig | Keep `/health/` responding on port 8000 behind the same host-header bypass and proxy chain. |
| Security settings | `config/settings.py`, `scripts/gcp/render_runtime_env.py`, ADR-008 rules | Preserve `DEBUG=false`, secure session/CSRF cookies, `SECURE_PROXY_SSL_HEADER`, `ALLOWED_HOSTS`, and trusted origins. |
| Logging | `config._logging_config.LOGGING`, `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()` | Prefer existing ECS JSON logging for application logs; if server access/error logging is changed, keep stdout/stderr container logging and avoid raw secret-bearing URLs. |
| Terminal capacity controls | `docs/architecture/terminal-websocket-capacity-847.md`, `TERMINAL_*` settings, `mission_control.consumers.SSHConsumer` | Remember that session caps are per ASGI process. More Gunicorn workers multiply process-local terminal capacity and FD usage. |
| Enforcement | `.gc/plan-rules.md`, ADR guard, Ruff, import-linter, actionlint/TFLint/kube tools when surfaces are touched | Runtime/bootstrap edits are architecture-sensitive and must pass the repo-required checks. |

## Cross-Cutting Layers

- Auth surface: websocket traffic must still enter through
  `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(...)))`. HTTP
  traffic must keep Django middleware, sessions, CSRF, OIDC/magic-link auth, and
  request ID behavior unchanged.
- Secret-handling surface: `entrypoint.sh` hydrates DB, app, OIDC, Guacamole,
  DC password, and Redis secret bundles before the web server starts. The final
  server command must not place secret values in process argv, generated env
  files, ConfigMaps, logs, or access-log lines. Passing only non-secret knobs
  such as bind address, port, worker class, worker count, timeouts, and log level
  in argv is acceptable.
- Env-binding shape: reuse `DJANGO_*`, `REDIS_*`, `TERMINAL_*`,
  `GUACAMOLE_*`, and cloud-provider env contracts as-is. Any new web-server
  knobs should be narrow process-manager knobs, not generic app settings and not
  provider-specific renderers.
- Config validators: Django settings must still fail closed for missing
  production `DJANGO_SECRET_KEY`, field encryption key, OIDC settings when
  required, and Redis TLS password/CA. Do not paper over startup failures with a
  Gunicorn preload, lazy import, or broad exception handling around ASGI app
  import.
- OS/process exposure: the process list may show Gunicorn master and worker
  command lines, so argv must contain no secrets. Multiple workers multiply DB
  connections, Redis channel-layer connections, websocket FDs, SSH sockets, and
  process-local terminal session caps. Fit defaults inside the 1Gi GCP pod limit
  and AWS instance/container FD limits.
- Network exposure: keep the bind target at `0.0.0.0:8000` inside the container
  and preserve the existing ALB/GCP ingress/TLS/proxy topology. Do not expose a
  separate Uvicorn port or sidecar service.
- Error-envelope surface: browser-facing HTTP and websocket failures should
  continue to come from existing Django views, consumers, close codes, and
  `shared.errors` classifiers. Do not introduce a server-wrapper exception
  hierarchy or leak raw worker exceptions to clients.
- Observability surface: container stdout/stderr, ECS-formatted application
  logs, ALB/GCP health checks, and existing probes are sufficient for this
  change. Useful server-level signal is worker boot/restart/exit and timeout
  events, without dumping request headers, cookies, query strings, or websocket
  payloads.
- Persistence surface: no database schema, migration, audit table, repository,
  DTO, or shared schema change is needed for the process-manager switch.

## Extensibility Seam

The seam is the portal web process-manager contract:

- application import: `config.asgi:application`
- bind address/port: container-local `0.0.0.0:8000`
- worker implementation: Gunicorn ASGI worker backed by Uvicorn
- worker count: environment-owned, with a conservative default
- timeout/shutdown policy: explicit enough to tune websocket and load-balancer
  behavior later without editing ASGI routing or deployment-specific commands

Keep this seam centralized in the image entrypoint unless a future issue
introduces a first-class chart/Terraform runtime setting.

## Gotchas

- Gunicorn workers are separate processes. Any process-local state, including
  terminal session registries and in-memory channel layers, is per worker. Local
  dev without Redis can still use the in-memory channel layer, but multi-worker
  deployments need the existing Redis channel layer for cross-process
  websocket/event coordination.
- Worker count changes affect capacity in both directions: more crash
  isolation and concurrency, but also more memory, DB connections, Redis
  connections, file descriptors, and startup work during migrations/static
  collection.
- The entrypoint currently runs migrations before starting the web process.
  That behavior is pre-existing; do not split migrations into Gunicorn hooks or
  run them per worker.
- Gunicorn access logs can contain request paths and query strings. Keep access
  logging on stdout only if it does not expose tokens, signed URLs, cookies, or
  raw websocket payloads; otherwise prefer application logs and platform logs.
- Official Uvicorn documentation currently warns that `uvicorn.workers` is
  deprecated. Check the chosen dependency/worker import against the locked
  versions in `uv.lock` and add a smoke test that imports the worker class.
- Dockerfile binary-copy mistakes fail only at container start. If the final
  command invokes `gunicorn` or `uvicorn` directly, the production stage must
  copy those console scripts from the builder.
- Existing technical docs still mention Daphne as the ASGI server. Update them
  in the implementation PR only after the runtime actually changes.

## Anti-Patterns

- Replacing `config.asgi:application` or duplicating ASGI routing to make the
  server command easier.
- Creating a second entrypoint, process supervisor, shell wrapper, settings
  module, Redis config, logging formatter, exception hierarchy, or deployment
  renderer for this runtime switch.
- Bypassing `entrypoint.sh` from Kubernetes, AWS user data, or Compose to run
  Gunicorn directly.
- Weakening `AllowedHostsOriginValidator`, session auth, CSRF, secure cookie
  settings, Redis TLS/AUTH validation, NetworkPolicies, ALB/GCP health checks,
  ADR guard, import-linter, or CI checks.
- Removing Daphne, changing `INSTALLED_APPS`, or changing local development
  behavior as an incidental cleanup without tests and explicit scope.
- Hard-coding production worker counts to a value that cannot be tuned per pod,
  instance size, or event load.

## Non-Goals

- No websocket consumer rewrite, terminal protocol change, Guacamole redesign,
  channel-layer redesign, or frontend reconnect-policy change.
- No new deployment component, sidecar, target group, Kubernetes service, or
  independently scalable terminal runtime.
- No schema, migration, repository, DTO, serializer, service-boundary, audit,
  or persistence change.
- No new auth system, secret store abstraction, logging framework, health-check
  endpoint, or workflow runner.
- No change to worker/scheduler commands except ensuring their existing command
  overrides still bypass the default web server command.

## Validation

For this implementation, run at minimum:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
cd shifter/shifter_platform && uv run ruff check .
cd shifter/shifter_platform && uv run ruff format --check .
```

If imports or deployment manifests/workflows are touched, also run the matching
repo gates from `.gc/plan-rules.md`: import-linter for Python imports,
actionlint for workflows, TFLint for Terraform, and kube-linter/kubeconform for
Kubernetes manifests.
