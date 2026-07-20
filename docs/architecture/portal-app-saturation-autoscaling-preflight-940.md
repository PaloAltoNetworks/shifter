# Portal App Saturation Autoscaling Preflight (#940)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/940>

## Scope Boundary

Issue #940 replaces the unfinished docs-only outcome of #851 with an AWS portal
autoscaling and observability change. The GitHub issue is the source of truth;
there is no Ground Control requirement for this run.

The implementation must make portal scale-out react to application saturation
before average EC2 CPU pins, and must make the scaling signal observable through
Terraform-managed alarms/dashboards and the event-load evidence surface.

Keep these concepts separate:

1. Traffic admission readiness: dependency-aware `/health` decides whether a
   target can receive traffic.
2. Portal web request saturation: ALB target latency, request volume per target,
   in-flight/queued HTTP work, and portal web-worker busy ratio.
3. Terminal capacity: process-local browser terminal session accounting from
   `mission_control.terminal_sessions`.
4. Backend worker backlog/liveness: SQS queue depth, message age, DLQs, and the
   #953 worker-container health supervisor.
5. Autoscaling control: the ASG policies, target values, cooldowns, alarms, and
   scale-in safeguards.

A single metric, endpoint, or namespace trying to encode all five repeats the
failure mode documented in #851.

## Architecture Decisions

- `/health` remains dependency readiness for ALB routing. Saturation signals must
  not make `/health` fail merely because the app is overloaded-but-live; that
  causes target churn instead of scale-out.
- Average EC2 CPU may remain a guardrail alarm, but it must not be the primary
  scale-out signal for request-path saturation. If scale-out moves to app/ALB
  saturation, scale-in must also respect low saturation and connection drain; do
  not leave CPU-low as the only scale-in condition.
- Use ALB-native metrics where they answer the question: `RequestCountPerTarget`
  is the traffic-per-target signal, and `TargetResponseTime` is the cheap
  leading proxy for request queueing. Confirm the exact Terraform/AWS ASG policy
  support for each metric before choosing target tracking versus alarm-backed
  step/simple scaling.
- Custom app metrics must use a portal-capacity namespace such as
  `Shifter/PortalCapacity`. Do not reuse `Shifter/WorkerHealth`; that namespace
  is for worker/scheduler container liveness and remediation.
- Name app signals precisely. "Worker busy ratio" means portal web worker busy
  ratio. SQS workers are background consumers. "Request queue depth" means HTTP
  request-path queueing/backpressure, not SQS backlog.
- Custom metrics are gauges/ratios with documented aggregation semantics:
  publish interval, dimensions, unit, statistic, denominator, and whether a
  value is per process, per instance, or fleet-wide. Terminal session counts are
  process-local unless explicitly aggregated.
- Metric dimensions must stay low-cardinality and non-secret. Environment/name
  prefix, ASG, load balancer, target group, and coarse signal names are
  acceptable. User IDs, session IDs, instance UUIDs, paths, query strings,
  cookies, Guacamole URLs, queue URLs, and exception strings are not.
- Dashboards/alarms belong in the existing portal Terraform surfaces and should
  follow Redis, messaging, worker-health, and engine-provisioner alarm
  conventions: explicit variables, environment wiring, `alarm_actions`, tags,
  and missing-data behavior stated in code.
- The event-load harness is the acceptance evidence path. Extend its AWS metrics
  adapter and report gaps instead of creating a second load-run report format or
  manually attaching CloudWatch screenshots.
- No ADR is required for adding AWS portal capacity metrics and policies inside
  existing module boundaries. A new repo-wide metrics framework, public
  diagnostics endpoint, provider-neutral metrics abstraction, or new runtime
  topology would require ADR/design-doc work.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #940 |
| --- | --- | --- |
| Portal ASG and EC2 IAM | `platform/terraform/modules/portal/ec2/{main.tf,variables.tf,outputs.tf}` | Add ASG policies, app-metric IAM, alarms, and dashboard resources here unless a module boundary already owns the resource. Do not create a parallel autoscaling module. |
| Portal ALB metrics and target group | `platform/terraform/modules/portal/alb/{main.tf,variables.tf,outputs.tf}` | Reuse the existing ALB/TG outputs and preserve TLS, WAF, `/admin` block, stickiness, health check, idle timeout, and deregistration delay. |
| Environment ownership | `platform/terraform/environments/{dev,prod}/portal/**` | Target values, thresholds, periods, cooldowns, alarm enablement/actions, and any metric-publication knobs are environment-owned tfvars/variables. |
| Runtime config hydration | `portal/ssm`, `platform/terraform/modules/portal/ec2/user_data.sh`, `scripts/portal-deploy/deploy_portal.sh` | New non-secret runtime knobs must be read by both fresh boot and SSM redeploy paths, validated before Docker argv, and mapped 1:1 to env vars. |
| ASGI process model | `entrypoint.sh`, `config.asgi_worker.ShifterUvicornWorker`, `config/asgi.py` | Treat Gunicorn/Uvicorn workers as the web-worker boundary. Do not add a second web entrypoint, supervisor, or sidecar for metric emission. |
| Django settings validation | `config/settings.py` `_env_int`, `_env_bool`, `_env_list` | Reuse fail-loud env parsing for app metric intervals/flags; do not add a second settings parser. |
| Readiness/liveness split | `config.middleware.HealthCheckMiddleware`, `config.health`, `config.health_checks`, Docker `HEALTHCHECK`, ALB health path | Do not encode overload into `/health`; verbose diagnostics stay in metrics/logs, not public probe output. |
| Terminal saturation source | `mission_control.terminal_sessions.TerminalSessionRegistry`, `mission_control.consumers.SSHConsumer`, `shared.enums.WebSocketCloseCode` | Reuse aggregate snapshots and close-code semantics. Do not claim global session counts without aggregation across workers/instances. |
| Backend queue pressure | `platform/terraform/modules/portal/messaging`, `shared/management/commands/run_worker.py` | Existing SQS queue depth/message age/DLQ alarms are backend-worker backlog, not HTTP request queue depth. Reuse them as adjacent signals only. |
| Worker liveness visibility | `platform/terraform/modules/portal/ec2/worker-health/**` and `aws_cloudwatch_metric_alarm.unhealthy_workers` | Keep worker remediation separate from portal web autoscaling. Do not make the worker-health agent restart `portal`. |
| Logging/error hygiene | `config._logging_config`, `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value`, `shared.errors` | Logs may contain aggregate counts and safe identifiers only; HTTP/websocket errors keep existing envelopes/close codes. |
| Cloud adapters | `shared.cloud` provider factories | There is no incumbent app metrics publisher. Either keep an AWS-only portal-capacity emitter scoped to this issue, or deliberately add a provider-neutral metrics protocol under `shared.cloud` with real tests. Do not hide CloudWatch calls in queue/secrets/storage adapters. |
| Load evidence | `uat/event-load-harness/**` | Extend `MetricsAdapter`/AWS CloudWatch specs/report rendering for #940 signals and named gaps. Do not import Django into the harness. |
| Enforcement | ADR guard, `.importlinter`, TFLint, actionlint, kube-linter/kubeconform as applicable | Do not weaken architecture, import, IaC, workflow, or Kubernetes checks to land metrics/scaling. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- Public ALB surface: keep HTTPS termination, WAF attachment, `/admin` fixed
  response, invalid-header dropping, public ingress limited to 80/443, target
  group stickiness, health path, idle timeout, and deregistration delay. Scaling
  metrics are not a reason to broaden listeners, security groups, or WAF policy.
- Auth surface: no new public diagnostics endpoint is needed for #940. If an
  implementation adds any operator HTTP surface, it must be authenticated and
  must not replace CloudWatch metrics. Websocket and HTTP routes keep
  `AllowedHostsOriginValidator`, Django sessions, CSRF, OIDC/magic-link gates,
  and existing view decorators.
- Secret-handling surface: app metric labels, logs, dashboards, and load reports
  must never include cookies, CSRF tokens, Guacamole signed URLs, Redis AUTH
  URLs, DB credentials/DSNs, SSH keys, queue URLs, raw request bodies, terminal
  streams, full env, or raw exception text.
- Env-binding shape: non-secret knobs flow through Terraform variables/tfvars,
  SSM Parameter Store when runtime-owned, `user_data.sh`, `deploy_portal.sh`,
  Docker env, and Django `_env_*` parsers. Avoid workflow-only variables or
  hard-coded thresholds in scripts.
- IAM/policy surface: the existing EC2 role grants `cloudwatch:PutMetricData`
  only for `Shifter/WorkerHealth`. App metrics need a separate least-privilege
  statement constrained by `cloudwatch:namespace`, not `cloudwatch:*` or a
  widened worker-health permission. Keep IMDSv2 and the current instance role
  boundary.
- OS/process exposure: Docker env and Gunicorn argv are visible to privileged
  host tooling. Only non-secret metric intervals, flags, namespace names, and
  thresholds may appear there. Metric emission should not shell out with secrets
  in argv, dump `docker inspect`, scrape full process env, or log command lines.
- Error-envelope surface: metric publication failures should be server-logged,
  bounded, and fail-soft for user traffic. They must not leak to browser
  responses or websocket payloads. Separately alarm on missing capacity metrics
  if missing data would make the scaling policy blind.
- Load-harness credential surface: the `uat/event-load-harness` AWS adapter is
  read-only CloudWatch collection. It must keep credentials out of argv and keep
  actor credentials in the existing 0600 manifest flow.

Maintainability incumbents the implementation must build on:

- `platform/terraform/modules/portal/ec2` for ASG policy, app metric IAM, and
  portal capacity alarms/dashboards.
- `platform/terraform/modules/portal/alb` for target group and ALB metric
  resource labels/outputs.
- `platform/terraform/environments/{dev,prod}/portal` for environment-owned
  thresholds and alarm actions.
- `portal/ssm`, `user_data.sh`, and `deploy_portal.sh` for any runtime metric
  knobs.
- `config/settings.py`, `entrypoint.sh`, `config/asgi.py`, and
  `config.asgi_worker` for process/runtime integration.
- `TerminalSessionRegistry` and `SSHConsumer` for terminal session metrics.
- `portal/messaging` and worker-health only as adjacent SQS/liveness signals.
- `uat/event-load-harness.metrics` and `report.py` for acceptance evidence.

Extensibility seam:

The durable seam is a named portal capacity signal contract:

- source: ALB, portal app process, terminal registry, or SQS;
- scope: per process, per instance, ASG/fleet, or target group;
- dimensions: low-cardinality and environment-scoped;
- statistic: `Average`, `Maximum`, `Sum`, p95/p99, or explicit proxy;
- denominator: worker count, terminal cap, request target, or none;
- consumer: scale-out, scale-in safeguard, dashboard only, or alarm only;
- runtime owner: Terraform-only, SSM-fed env, or app-derived.

The next reasonable variation should be a parameter change, not a redesign:
changing instance size, adding a second event profile, moving to GCP/HPA,
introducing a dedicated terminal target group, or switching the primary scaling
signal should not require rewriting terminal authorization, health probes,
workflow deploy logic, or the load-report schema.

## Whole-Repo Scope

Likely in scope for implementation:

- AWS Terraform: `platform/terraform/modules/portal/{ec2,alb,ssm,messaging,redis}`
  and `platform/terraform/environments/{dev,prod}/portal/**`.
- Portal runtime: `shifter/shifter_platform/config/settings.py`,
  `entrypoint.sh`, `config/asgi.py`, `config/asgi_worker.py`, and a narrow
  config/middleware or capacity module if custom app metrics are emitted.
- Terminal session metrics: `mission_control/terminal_sessions.py`,
  `mission_control/consumers.py`, and their tests if active session counts or
  utilization are exported.
- Evidence tooling: `uat/event-load-harness/event_load_harness/metrics/**`,
  `report.py`, `cli.py`, README/sample report, and tests.
- Deploy workflow/scripts only if new runtime env values or output discovery are
  needed; keep SSM deploy behavior in `scripts/portal-deploy/deploy_portal.sh`,
  not inline workflow shell.

Usually out of scope:

- GCP/Kubernetes HPA or BackendConfig changes, unless the issue is explicitly
  expanded for provider parity.
- Health/readiness endpoint redesign, ASGI process-manager swap, terminal
  gateway extraction, Guacamole scaling redesign, DB connection lifecycle
  change, SQS worker schema change, or new persistence.

## Gotchas

- `RequestCountPerTarget` can scale on traffic volume before latency rises, but
  it does not prove queueing. `TargetResponseTime` shows user-visible latency,
  but dependency failures can also move it. Correlate with `/health`, 5xx,
  rejected connections, terminal close codes, and backend metrics.
- A true HTTP request queue depth may not be directly observable inside Django
  because queued requests may wait before middleware runs. Do not label
  in-flight requests or SQS backlog as "queue depth" unless the metric
  definition says exactly what it measures.
- Gunicorn workers are separate processes. A per-process busy ratio or terminal
  session gauge needs an aggregation contract. `Sum`, `Average`, and `Maximum`
  answer different questions.
- Terminal session caps are process-local. Fleet terminal utilization needs
  `in-service instances * PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS` as the
  denominator unless shared accounting is deliberately introduced.
- Scale-in is risky during websocket/RDP/SSH traffic. Respect target-group
  deregistration delay, ASG termination drain, Docker stop timeout, and
  reconnect amplification from #931.
- Custom metrics can disappear during worker boot, deploy, failed imports, or
  CloudWatch API failures. Missing data behavior must not silently scale in a
  saturated fleet or hide the fact that the control loop is blind.
- Dev's committed baseline has `enable_autoscaling=false`. Acceptance for
  "triggers scale-out" needs an ASG-enabled environment, not a single-instance
  load run.
- `enable_redis` is channel-layer wiring posture and is independent of
  `enable_autoscaling` (ADR-018). Do not infer Redis/channel behavior from ASG
  mode.
- High-cardinality CloudWatch dimensions are expensive and hard to alarm on.
  Do not dimension by user, request path, instance UUID, session ID, image tag,
  queue URL, or command line.

## Anti-Patterns

- Making `/health` fail under overload to force replacement or scale-out.
- Treating average EC2 CPU, SQS backlog, Redis connections, terminal sessions,
  and web request queueing as one interchangeable "load" metric.
- Reusing `Shifter/WorkerHealth` for portal web saturation metrics.
- Leaving CPU-low as the sole scale-in path after adding app-level scale-out.
- Creating duplicate health endpoints, settings parsers, deployment scripts,
  Terraform modules, load harnesses, logging formats, exception hierarchies, or
  metric schemas.
- Emitting metrics from request handlers synchronously enough to add latency to
  the path being measured.
- Shelling out to `aws cloudwatch put-metric-data` from the app process with
  secret-bearing env available in argv/log surfaces.
- Logging raw request bodies, terminal input/output, cookies, Guacamole URLs,
  Redis auth URLs, DB settings, secret ARNs as values, or raw exception text.
- Weakening WAF, `/admin` blocking, host/origin validation, CSRF, Redis
  fail-closed config, ADR guard, TFLint, actionlint, import-linter,
  kube-linter, or kubeconform to make a load run or scaling test pass.

## Non-Goals

- No implementation in this preflight note.
- No new public diagnostics endpoint, metrics platform, Prometheus/statsd
  deployment, database schema, repository, DTO, serializer, service layer, or
  exception framework.
- No redesign of `/health`, ALB target health, ASGI worker model, terminal
  websocket protocol, Guacamole token broker, CTF scoring, SQS worker behavior,
  channel-layer selection, Redis AUTH/TLS, or RDS connection lifetime.
- No GCP autoscaling/HPA parity in #940 unless the issue is explicitly expanded.
- No Ground Control traceability work; this is requirement-free and issue
  driven.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must also run the stack-native checks for touched
surfaces: TFLint for Terraform, `uv run ruff check .` and
`uv run ruff format --check .` for Python under `shifter/shifter_platform`,
import-linter for import-boundary changes, `uv run pytest` in
`uat/event-load-harness` for evidence-tool changes, actionlint for workflow
changes, and kube-linter/kubeconform for Kubernetes changes.
