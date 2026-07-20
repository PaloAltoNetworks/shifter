# Terminal Capacity Tunables Preflight (#930)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/930>

## Scope Boundary

Issue #930 corrects the portal terminal capacity model after the production web
runtime moved from one ASGI process to Gunicorn with multiple Uvicorn workers.
The work is configuration wiring, capacity accounting, documentation, and load
test verification. It is not a terminal runtime extraction, websocket protocol
redesign, autoscaling redesign, or new persistence feature.

The GitHub issue is the authoritative contract. There is no Ground Control
requirement for this run.

## Architecture Decisions

- Keep terminal SSH streaming in the existing portal ASGI runtime unless the
  load-test evidence creates a separate runtime follow-up. `SSHConsumer` and
  `engine.ssh.SSHConnection` remain the transport boundary for this issue.
- Do not let `TERMINAL_MAX_SESSIONS` mean two different things. Today it is
  process-local because `mission_control.terminal_sessions.session_registry` is
  process-local. If the implementation keeps that design, docs, comments, SSM
  names/descriptions, and load reports must state the effective capacity:

  ```text
  per-instance cap = PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS
  per-user worst-case cap = PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS_PER_USER
  fleet cap = in-service instances * PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS
  ```

- If the implementation instead chooses a per-instance cap, it must introduce
  real shared accounting with atomic reserve/release and expiry semantics before
  claiming an instance-wide limit. A process-local counter plus documentation is
  not a per-instance cap.
- Runtime knobs are environment-owned, non-secret configuration. For AWS, wire
  them through the existing Parameter Store path under
  `/shifter/<environment>/portal`, the `portal/ssm` module, and both container
  hydration paths: first-boot `user_data.sh` and SSM redeploy
  `scripts/portal-deploy/deploy_portal.sh`.
- "Without an image rebuild" means the same image can be restarted/converged
  with new environment values from SSM. It does not mean a running Gunicorn
  master or already-started worker hot-reloads changed environment variables.
- Size `PORTAL_WEB_WORKERS` as an explicit per-environment runtime setting
  matching the instance/pod CPU budget. Do not add an image-time `nproc`
  heuristic: container CPU limits, Kubernetes nodes, and AWS instance types can
  make that misleading. If a future implementation derives workers from
  instance type, centralize that policy in Terraform/runtime config, not in a
  second process-manager wrapper.
- Keep the autoscaling problem separate. CPU-only scale-out and HTTP
  concurrency ceilings can be measured and reported by the load harness, but
  terminal-cap wiring must not silently redesign ALB/ASG policy in this issue.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #930 |
| --- | --- | --- |
| ASGI process manager | `shifter/shifter_platform/entrypoint.sh`, `docs/architecture/portal-asgi-process-manager-preflight-174.md` | Reuse the Gunicorn/Uvicorn command and env-owned knobs; do not add a second web entrypoint or supervisor. |
| Terminal capacity accounting | `mission_control.terminal_sessions.TerminalSessionRegistry`, `mission_control.consumers.SSHConsumer` | Preserve or explicitly replace the process-local accounting model; do not imply global accounting without a shared store. |
| Terminal settings parser | `config/settings.py` `_env_int` and `TERMINAL_*` settings | Reuse existing Django settings names and fail-loud integer parsing; add narrow validation rather than a parallel config layer. |
| AWS SSM config path | `platform/terraform/modules/portal/ssm/{variables.tf,main.tf}` | Add non-secret String parameters the same way `channel-layer-backend` is published. |
| AWS env hydration | `platform/terraform/modules/portal/ec2/user_data.sh`, `scripts/portal-deploy/deploy_portal.sh` | Fresh boot and SSM redeploy must read the same parameter names and emit the same Docker env. |
| Environment roots | `platform/terraform/environments/{dev,prod}/portal/{variables.tf,main.tf,terraform.tfvars}` | Keep deployed defaults explicit in tfvars/locals; do not hide event capacity policy inside the image. |
| GCP runtime env | `scripts/gcp/render_runtime_env.py`, `platform/k8s/gcp/base/web-deployment.yaml` | If these knobs become cross-provider defaults, render them through the existing GCP env renderer/ConfigMap path; do not fork a GCP-only parser. |
| Channel-layer posture | `docs/architecture/portal-channel-layer-backend.md`, `config/_channels.py` | Reuse Redis config only for channel-layer concerns unless shared terminal accounting is explicitly chosen; terminal bytes must not flow through Redis. |
| Load evidence | `uat/event-load-harness`, `docs/architecture/event-load-harness-preflight-926.md` | Report process model, worker count, cap scope, effective caps, close codes, reconnects, and provider metrics. |
| Websocket close codes | `shared.enums.WebSocketCloseCode` | Keep over-cap rejection on the shared `SERVICE_UNAVAILABLE` code unless a scoped client change updates both sides. |
| Audit/logging | `risk_register.services.audit_session_event`, `config._logging_config`, `shared.log_sanitize` | Keep connect/disconnect audit semantics; log aggregate counts and safe identifiers only. |
| Enforcement | ADR guard, import-linter, TFLint, actionlint, kube-linter/kubeconform when surfaces are touched | Do not weaken repo guardrails to make runtime config easier. |

## Cross-Cutting Layers

- Auth surface: websocket traffic must continue through
  `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(...)))` in
  `config/asgi.py`. HTTP bootstrap and Guacamole paths keep Django sessions,
  CSRF, and existing auth decorators. Capacity settings must not add bypass
  routes or test-only auth.
- Authorization and validation surface: `engine.services.connect_terminal()` /
  `get_ssh_connection_info()` remain authoritative for user ownership, active
  range, range readiness, instance lookup, SSH key reference, host, username,
  and OS/tmux behavior. Do not duplicate that logic in deploy scripts,
  Terraform, load tests, or JavaScript.
- Secret-handling surface: all #930 knobs are non-secret integers. Store them
  as SSM `String` parameters and Docker env values only. Do not move SSH keys,
  Guacamole tokens, Redis AUTH material, DB credentials, or signed URLs into
  SSM/tfvars to make tuning easier.
- Env-binding shape: app terminal settings use `TERMINAL_*` in
  `config/settings.py`; process-manager settings use `PORTAL_WEB_*` in
  `entrypoint.sh`. Keep those namespaces distinct. SSM names should map
  directly to env vars and descriptions must say whether a cap is per process
  or instance-wide.
- Config validators: add Terraform validation and shell-side numeric validation
  for SSM-fed values before they reach Docker. Existing `_env_int` is still the
  Django fail-loud backstop. Deployed tfvars should keep workers, caps, and
  timeouts positive unless a separately documented break-glass path deliberately
  disables a terminal limit.
- OS/process exposure: Docker env and Gunicorn argv are visible to privileged
  host operators and process tooling. That is acceptable only because these
  knobs are non-secret. Multiple workers multiply DB connections, Redis
  connections, websocket FDs, SSH sockets, memory, startup work, and
  process-local terminal caps.
- Error-envelope surface: over-cap terminal connections should still fail
  through authored websocket close codes, not raw exceptions. Startup config
  errors should fail the container clearly and surface through existing health
  checks, not as partial service with hidden defaults.
- Logging and observability: startup logs may include non-secret worker count,
  cap scope, and effective cap. Runtime logs should keep aggregate registry
  snapshots and safe identifiers; never log terminal input/output, private keys,
  full Guacamole URLs, Redis AUTH URLs, cookies, or raw SSM values that might
  later become secret-bearing.
- Persistence surface: `risk_register` session audit rows are the existing
  durable record. Do not add a terminal-session table or migration for #930
  unless the design explicitly chooses shared per-instance accounting and proves
  Redis/ephemeral accounting is insufficient.
- Workflow surface: AWS deploy workflows already update image parameters and
  converge instances through `scripts/portal-deploy/deploy_portal.sh`. Extend
  that path rather than reintroducing inline heredocs or a second SSM command
  body. Manual event-time SSM overrides, if allowed, must be reconciled back to
  tfvars after the event because Terraform owns the steady-state parameters.

## Extensibility Seam

The durable seam is a portal runtime capacity contract:

- worker policy: `PORTAL_WEB_WORKERS`, tied to environment CPU budget;
- web timeout policy: `PORTAL_WEB_TIMEOUT` and
  `PORTAL_WEB_GRACEFUL_TIMEOUT`;
- terminal cap policy: total cap, per-user cap, idle timeout, max session
  timeout, read poll interval, and explicit cap scope (`process` unless shared
  accounting is implemented);
- deployment source: AWS SSM/tfvars now, GCP env renderer if cross-provider
  tuning is needed;
- evidence contract: load reports state worker count, cap scope, effective
  instance/fleet caps, and observed rejection point.

The next reasonable variation is changing instance size or moving an event from
AWS single-instance to ASG/GCP. That should be a tfvars/rendered-env change plus
a load-harness run, not a rewrite of terminal authorization, frontend protocol,
or process-manager code.

## Whole-Repo Scope

Surfaces likely in scope for implementation:

- `shifter/shifter_platform/entrypoint.sh` and
  `shifter/shifter_platform/config/settings.py` for runtime env parsing and
  comments.
- `shifter/shifter_platform/config/asgi.py` for the stale process-count
  comment.
- `mission_control/terminal_sessions.py`, `mission_control/consumers.py`, and
  existing terminal consumer tests if the accounting scope changes.
- `platform/terraform/modules/portal/ssm/**`,
  `platform/terraform/modules/portal/ec2/user_data.sh`, and
  `scripts/portal-deploy/deploy_portal.sh` for AWS runtime config wiring.
- `platform/terraform/environments/{dev,prod}/portal/**` for environment-owned
  values and validation.
- `scripts/portal_deploy/tests/**`, platform tests, and config tests for
  structural invariants.
- `uat/event-load-harness/**` if the report schema needs to expose cap scope
  and effective cap.
- `scripts/gcp/render_runtime_env.py` and `platform/k8s/gcp/**` only if #930
  intentionally makes these knobs cross-provider tunables.

## Gotchas

- Four Gunicorn workers turn a per-process cap of 200 into roughly 800 sessions
  per instance, and a per-user cap of 10 into a worst-case 40 sessions per user
  per instance. ASG desired capacity multiplies this again.
- Load balancer behavior can hide the true limit. ALB idle timeout, target
  stickiness, reconnect policy, and client FD limits all affect observed
  websocket capacity.
- Worker count changes increase HTTP crash isolation but also consume memory,
  DB connections, Redis connections, file descriptors, and CPU. A higher worker
  count can reduce headroom even if terminal cap math looks larger.
- `CHANNEL_LAYER_BACKEND=redis` is required for cross-process notification
  delivery, but it does not make terminal session accounting global. Redis
  channel-layer metrics are not terminal byte-stream metrics.
- Existing `TERMINAL_*` env semantics allow `<= 0` to disable individual
  limits. That can be useful in tests but is a risky deployed posture; tfvars
  validation should make disabled caps deliberate, not accidental.
- `user_data.sh` currently builds a Docker env string for `eval docker run`;
  any SSM-fed value added there needs strict validation before interpolation.
- Updating an SSM parameter does nothing to already-started containers until
  the deploy/converge path restarts them with the new environment.

## Anti-Patterns

- Claiming per-instance terminal limits while using only the process-local
  registry.
- Routing terminal input/output through Redis, shared notifications, SQS, a DB
  table, or load-test hooks to get global accounting.
- Creating a second settings parser, entrypoint, deploy script, SSM prefix,
  Terraform module, exception hierarchy, audit table, or terminal DTO.
- Hard-coding worker counts in the image, JavaScript, ASGI routing, or docs
  instead of environment-owned runtime config.
- Inferring Redis/channel-layer posture from `enable_autoscaling`.
- Treating average CPU scale-out as proof that websocket/terminal capacity is
  safe.
- Logging terminal streams, credentials, Guacamole URLs, Redis auth URLs,
  cookies, or raw exception text in capacity artifacts.
- Weakening ASGI host/origin checks, session auth, CSRF, Terraform validation,
  ADR guard, actionlint, TFLint, import-linter, kube-linter, or kubeconform.

## Non-Goals

- No terminal gateway, dedicated ASGI service, target-group split, or frontend
  protocol migration in #930 unless the issue is explicitly expanded.
- No new authentication system, secret-store abstraction, logging framework,
  metrics platform, or persistent terminal-session schema for process-local
  caps.
- No autoscaling policy redesign, ALB timeout change, RDS/Redis sizing change,
  Guacamole redesign, or CTF scoring change.
- No promise of hot in-process reload for Gunicorn workers; restart/converge is
  the runtime boundary.
- No Ground Control traceability work; this is requirement-free and issue
  driven.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must also run the stack-native checks for touched
surfaces: Django/config tests and terminal consumer tests for Python changes,
`scripts/portal_deploy` tests for the SSM redeploy path, TFLint for Terraform,
actionlint for workflow changes, and kube-linter/kubeconform for Kubernetes or
GCP runtime changes.
