# AWS Long-Lived Connection Drain Preflight (#931)

Status: pre-implementation guidance

Date: 2026-06-20

Issue: GitHub #931, "alb: set idle timeout, deregistration delay, and drain
for long-lived WS/SSH/RDP"

This is a requirement-free preflight. The GitHub issue title, body, and
acceptance criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

Treat this as AWS connection-lifecycle hardening for the existing portal and
Guacamole runtime. The defect is that long-lived browser terminal, notification,
range-status, and Guacamole RDP/SSH connections can outlive the default ALB,
target-group, Docker, Gunicorn, and ASG refresh timing contracts.

Keep these concepts separate:

1. ALB idle timeout: how long an otherwise quiet front-end/back-end connection
   may sit before the ALB closes it.
2. WebSocket keepalive: protocol/application traffic that proves an idle
   websocket is still live before the ALB idle timeout expires.
3. Target deregistration delay: how long the target group lets existing
   connections drain after a target stops receiving new traffic.
4. Container graceful stop: how long Docker gives Gunicorn/Uvicorn and workers
   to handle SIGTERM before SIGKILL.
5. ASG termination drain: how long instance refresh/scale-in keeps a
   terminating instance in a bounded wait state while ALB draining and process
   shutdown finish.
6. Client reconnect/backoff: browser behavior after an unavoidable close,
   measured by workload, not assumed to be uniform.

Do not solve one layer by silently relying on another layer's default. The
implementation should make each connection-lifecycle value explicit and size
the values relative to one another.

## Architecture Decisions

- Keep the AWS portal ALB as the public TLS, WAF, `/admin` block, and
  path-routing boundary. Do not introduce a second public listener, bypass the
  shared ALB, or expose Guacamole/RDP/SSH directly.
- Add explicit ALB and target-group timing inputs at the Terraform module
  boundaries, then pin environment values in the dev/prod portal roots. Do not
  hardcode event-specific timings in `aws_lb`, `aws_lb_target_group`, workflow
  shell, or user-data bodies.
- Apply drain timing to both long-lived target groups on the shared ALB:
  the portal target group for Django/Channels websockets and the Guacamole
  target group for `/guacamole` browser sessions.
- Keep WebSocket keepalive centralized in the ASGI/server runtime if Uvicorn's
  websocket ping covers the deployed Gunicorn worker path. Only add
  consumer-level pings if the built image proves the server-level path is not
  actually sending keepalive frames through ALB.
- Preserve `scripts/portal-deploy/deploy_portal.sh` as the SSM deploy body.
  Container stop behavior belongs there and in its tests, not in duplicated
  inline workflow commands.
- Extend the existing ASG lifecycle-hook model with a distinct termination
  drain contract. Do not reuse the launch hook name for termination completion,
  and do not make launch bootstrap success depend on termination-drain logic.
- Drain is bounded reliability, not session migration. Existing terminal and
  Guacamole sessions may still close after the chosen drain window; the
  acceptance test must prove the intended 10-minute idle and refresh cases.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #931 |
| --- | --- | --- |
| Portal ALB | `platform/terraform/modules/portal/alb/main.tf` and `variables.tf` | Add explicit ALB idle timeout and portal target-group deregistration delay here; preserve TLS policy, WAF, `/admin` fixed response, access-log gating, stickiness, and header-drop posture. |
| Guacamole target group | `platform/terraform/modules/guacamole/alb.tf` and `variables.tf` | Add explicit Guacamole deregistration delay here; preserve `/guacamole` path routing, target type `ip`, HTTP backend exception, and stickiness. |
| Environment ownership | `platform/terraform/environments/{dev,prod}/portal/{variables.tf,terraform.tfvars,main.tf}` | Pin values per environment. Dev can use shorter drain if cost/iteration requires it, but prod/event values must be explicit. |
| Portal ASG | `platform/terraform/modules/portal/ec2/main.tf`, `variables.tf`, `outputs.tf`, `user_data.sh` | Reuse the existing launch lifecycle hook and IAM permission shape, but create separate termination-drain naming/outputs if a hook is added. |
| Deploy topology | `scripts/portal_deploy/portal_deploy.py` and `_shifter-platform.yml` deploy job | Keep single-instance vs ASG selection derived from Terraform outputs. Do not add a GitHub variable as a second topology source. |
| SSM deploy body | `scripts/portal-deploy/deploy_portal.sh` and `scripts/portal_deploy/tests/test_deploy_portal_script.py` | Change Docker stop behavior here and cover it with the existing subprocess-style tests. Avoid inline workflow redeploy logic. |
| Portal web runtime | `shifter/shifter_platform/entrypoint.sh`, `pyproject.toml`, `tests/test_asgi_worker_smoke.py` | Keep `config.asgi:application` under Gunicorn/Uvicorn. If keepalive knobs are added, make them non-secret env-owned process-manager settings and smoke-test the worker/backend import contract. |
| ASGI/websocket auth | `config/asgi.py`, `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, `mission_control/routing.py`, `shared/routing.py` | Keep host/origin/session gates unchanged. Do not add token-in-query reconnect shortcuts. |
| Terminal transport | `mission_control.consumers.SSHConsumer`, `mission_control.terminal_sessions`, `static/js/terminal.js` | Preserve existing close codes, per-process caps, idle/max-duration timeouts, and exponential reconnect behavior unless #931 explicitly changes them with tests. |
| Guacamole broker | `mission_control.guacamole`, `mission_control.views._guacamole`, `static/js/terminal-guacamole.js` | Keep JSON-auth URL creation and token-readiness retries in the existing broker; do not make ALB drain work a Guacamole auth redesign. |
| Channel layer | `config/_channels.py`, ADR-018, SSM `channel-layer-backend` parameter | Do not infer Redis/channel behavior from ASG mode. Drain and keepalive changes must work with the explicit channel-layer posture. |
| Health/readiness | `config.middleware`, `config.health`, `docs/architecture/portal-health-readiness-preflight-477.md` | Keep `/health` dependency-aware and health-probe-specific. Do not make health checks the drain signal or broaden `ALLOWED_HOSTS`. |
| Observability and logs | `config._logging_config`, `shared.log_sanitize.safe_log_value()`, ALB access logs, ECS/Docker logs | Log timings, states, close codes, instance ids, ASG names, and command ids only. Never log cookies, signed Guacamole URLs, terminal bytes, secrets, or rendered env dumps. |
| Prior guidance | `terminal-websocket-capacity-847.md`, `portal-asgi-process-manager-preflight-174.md`, `guacamole-first-click-rdp-preflight-395.md`, `event-load-harness-preflight-926.md` | Build on the existing workload boundaries; do not introduce duplicate schemas, DTOs, validators, exception hierarchies, or deployment renderers. |

## Cross-Cutting Layers

Security layers the intended design must satisfy:

- Public ALB surface: keep HTTPS termination, WAF attachment, `/admin` fixed
  response, `drop_invalid_header_fields = true`, internet ingress limited to
  80/443, and outbound SG behavior unchanged. `idle_timeout` is a load-balancer
  attribute, not a reason to broaden listener or security-group exposure.
- Target-group surface: portal and Guacamole backends remain private HTTP
  targets behind the ALB security group. Changing `deregistration_delay` must
  not change target protocol, target type, health-check path, matcher, or
  stickiness semantics without separate evidence.
- Auth surface: all websockets still enter through
  `AllowedHostsOriginValidator(AuthMiddlewareStack(...))`; Guacamole launch
  still uses authenticated, CSRF-protected Mission Control POSTs. Reconnect
  support must not use bearer tokens in URLs, local storage, or logs.
- Secret-handling surface: all new lifecycle knobs are non-secret numeric
  configuration. Keep them in Terraform variables, tfvars, SSM non-secret
  parameters if runtime env hydration is needed, or container env. Do not put
  Guacamole tokens, RDP passwords, SSH keys, Redis URLs, or Secret Manager
  values in argv, SSM command strings, workflow logs, access logs, or test
  artifacts.
- Env-binding shape: Django runtime values continue through `config.settings`
  parsers such as `_env_int`; AWS deploy runtime values continue through the
  `portal/ssm` plus `deploy_portal.sh` contract. Do not add a second
  provider-specific settings parser or a workflow-only env contract.
- Config validators: Terraform module inputs should include validation for
  legal AWS ranges and value ordering where Terraform can check it. Python
  settings should fail clearly for invalid keepalive values. Workflow changes
  must pass `actionlint`; Terraform changes must pass TFLint; architecture
  changes must pass ADR guard.
- IAM/policy surface: if termination lifecycle actions are completed by
  instance-side code, reuse the scoped `autoscaling:CompleteLifecycleAction`
  pattern already present for launch hooks. Do not grant wildcard Auto Scaling
  mutation beyond the current ASG resource need. A passive timeout-only
  termination hook still needs explicit operator documentation.
- OS/process exposure: `docker stop --time <N>` and Gunicorn arguments are
  visible in process/command logs, so only non-secret timing values may appear
  there. The Docker stop timeout must exceed `PORTAL_WEB_GRACEFUL_TIMEOUT` and
  remain below the ASG termination drain window.
- Error-envelope surface: browser-visible terminal failures should continue to
  use `WebSocketCloseCode` and existing terminal UI messages. Guacamole errors
  should continue through the broker's sanitized HTTP/JSON envelopes. Do not
  leak raw ALB, SSM, Docker, or Guacamole exception text to users.
- Persistence surface: no new durable session table is required for this issue.
  Existing audit/session records and aggregate test evidence are sufficient
  unless a separate product requirement asks for session migration or history.

Maintainability incumbents the implementation must build on:

- `platform/terraform/modules/portal/alb` and `modules/guacamole/alb.tf` for
  ALB/target-group timing.
- `platform/terraform/modules/portal/ec2` for ASG lifecycle hooks, IAM, launch
  template user-data, and outputs.
- `scripts/portal-deploy/deploy_portal.sh` for SSM-driven container lifecycle.
- `_shifter-platform.yml` only for invoking existing deploy/topology helpers
  and instance refresh, not for embedding new container lifecycle logic.
- `entrypoint.sh` for Gunicorn/Uvicorn process-manager defaults.
- `config.settings`, `mission_control.consumers`, `terminal.js`, and
  `mission_control.guacamole` for app/runtime keepalive and reconnect surfaces.

Extensibility seam:

The seam is an environment-owned connection lifecycle contract:

- `alb_idle_timeout_seconds`
- `portal_target_deregistration_delay_seconds`
- `guacamole_target_deregistration_delay_seconds`
- `portal_websocket_keepalive_interval_seconds`
- `portal_web_graceful_timeout_seconds`
- `docker_stop_timeout_seconds`
- `asg_termination_drain_timeout_seconds`
- `asg_instance_refresh_min_healthy_percentage` / checkpoint or warmup values

Keep these as explicit parameters at the layer that consumes them. The next
reasonable variation, such as longer event drains in prod, shorter dev drains,
or a future dedicated terminal target group, should be a tfvars/runtime-config
change rather than a source patch across unrelated scripts.

## Whole-Repo Scope

In scope for the implementation:

- AWS Terraform:
  `platform/terraform/modules/portal/alb/**`,
  `platform/terraform/modules/guacamole/**`,
  `platform/terraform/modules/portal/ec2/**`,
  `platform/terraform/modules/portal/ssm/**` if new runtime env hydration is
  needed, and `platform/terraform/environments/{dev,prod}/portal/**`.
- AWS deploy workflow:
  `.github/workflows/_shifter-platform.yml` only where ASG refresh preferences
  or invocation of existing helpers must change.
- Deploy helper and tests:
  `scripts/portal-deploy/deploy_portal.sh`,
  `scripts/portal_deploy/portal_deploy.py` if ASG drain verification becomes a
  reusable helper, and `scripts/portal_deploy/tests/**`.
- Portal runtime:
  `shifter/shifter_platform/entrypoint.sh`,
  `config/settings.py`, `tests/test_asgi_worker_smoke.py`, terminal websocket
  tests, and frontend terminal tests if keepalive or reconnect behavior changes.
- Evidence:
  `uat/event-load-harness` can be reused or extended for deployed idle/drain
  evidence if the implementation needs automated acceptance evidence.

Usually out of scope:

- GCP Helm/Kubernetes ingress and BackendConfig, unless a separate GCP issue is
  opened.
- Engine range provisioning, SSH credential resolution, CTF scoring, Guacamole
  JSON-auth model, notification schema, database migrations, and shared cloud
  provider factories.

## Gotchas And Anti-Patterns

- Do not set ALB idle timeout alone. If no explicit keepalive reaches the ALB
  before that timeout, idle websockets remain vulnerable to silent reaping.
- Do not assume Uvicorn's default websocket ping is active in the built
  Gunicorn/Uvicorn worker path. Prove it or pin an explicit runtime setting.
- Do not size `deregistration_delay`, Docker stop timeout, Gunicorn graceful
  timeout, ASG lifecycle heartbeat, and instance-refresh warmup independently.
  Misordered values create false drain windows where the instance or process is
  already gone.
- Do not conflate portal terminal websocket reconnect behavior with Guacamole
  RDP session survival. Guacamole browser sessions are served by
  guacamole-client/guacd through `/guacamole` and need their own drain evidence.
- Do not treat target-group stickiness as a session-drain substitute. Stickiness
  helps affinity while a target is healthy; deregistration and instance
  termination still need explicit timing.
- Do not complete a termination lifecycle hook before the ALB target has entered
  draining and the bounded wait has elapsed, unless the design intentionally
  chooses passive timeout-only drain.
- Do not introduce new terminal DTOs, duplicate reconnect libraries, exception
  hierarchies, SSM deploy scripts, Terraform modules, or app-specific schema
  layers for timing values.
- Do not weaken WAF, `/admin` blocking, health checks, `AllowedHostsOriginValidator`,
  CSRF, Redis fail-closed config, ADR guard, TFLint, actionlint, or deploy
  fail-loud behavior to make a drain test pass.
- Do not log terminal streams, cookies, session ids beyond existing sanitized
  identifiers, signed Guacamole URLs, auth tokens, SSH keys, RDP passwords, or
  rendered environment dumps.

## Non-Goals

- No implementation in this preflight note.
- No session migration across instances, shared terminal gateway, new public
  ALB/listener, durable Guacamole connection model, or browser protocol
  redesign.
- No redesign of auth, OIDC, CSRF, channel-layer selection, Redis TLS/AUTH,
  health/readiness, worker queues, database schema, audit persistence, or range
  provisioning.
- No GCP/Kubernetes parity change unless a separate issue scopes it.
- No broad "make deploy slower" workaround. Every added wait must map to a
  connection-lifecycle layer and have a bounded value.

## Validation

For this documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must additionally run the stack-native checks for
the surfaces they touch:

```bash
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
cd shifter/shifter_platform && uv run ruff check .
cd shifter/shifter_platform && uv run ruff format --check .
```

Acceptance evidence should include an idle terminal surviving 10 minutes and an
active terminal plus active RDP session surviving an ASG instance refresh in the
target AWS environment.
