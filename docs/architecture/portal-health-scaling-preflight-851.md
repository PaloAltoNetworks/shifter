# Portal Health and Scaling Preflight (#851)

Status: pre-implementation guidance

Date: 2026-06-03

Tracking issue: <https://github.com/Brad-Edwards/Shifter/issues/851>

## Scope Boundary

Issue #851 is diagnostic and design work under the live-event remediation
parent #846. The shipping contract is to record the portal's current scaling
and health posture, map observed event-time symptoms to candidate signals,
and define the evidence bar that any follow-up implementation issue must
clear before changing a metric, threshold, alarm, or runtime topology.

Four concerns must stay separate in the analysis and in any follow-up
implementation:

1. Process liveness (the local Daphne process can answer a TCP socket).
2. Dependency readiness (Postgres, Redis/channel layer, Secrets Manager,
   storage, the Guacamole bootstrap path are reachable and serving).
3. Overload observability (the portal is live and the dependencies answer,
   but request handling is regressing or queueing).
4. Autoscaling control (the signal a scale-up/scale-down policy reacts to).

A single endpoint or metric trying to encode all four is the failure mode
this preflight exists to prevent. Making ALB health fail on transient
overload causes target churn instead of scaling. Using a single coarse
EC2-average metric for autoscaling lets a hot Python process saturate
user-facing paths before the alarm fires.

Adjacent contracts this preflight respects but does not pre-empt:

- `/health` response body, status codes, and dependency probe set are owned
  by #477.
- The single-process Daphne runtime model is owned by #174.
- Browser terminal websocket capacity envelope is owned by #847 and its
  preflight at `terminal-websocket-capacity-preflight-847.md`.
- The portal autoscaling MVP (ASG, Channels Redis, stickiness) was
  established by the closed #187.

## Architecture Decisions

- Portal capacity has two distinct decision surfaces: a health/readiness
  surface that gates traffic admission (the ALB target-group health probe)
  and a scaling surface that drives ASG capacity. The current configuration
  conflates them: both use a single binary `/health` for admission and a
  single EC2-average `CPUUtilization` for scaling. Future work must treat
  them as independently parameterized.
- The health surface stays coarse and public. Verbose dependency state and
  per-process saturation diagnostics go to logs, CloudWatch metrics, or an
  internal/admin surface, not to a public probe.
- The scaling surface is evidence-driven. EC2 average CPU, ALB target
  latency, ALB 5xx, ALB rejected connections, custom application metrics,
  and Daphne worker reshaping (issue #174) are all candidates. None is
  pre-selected by this preflight.
- Overload observability is a separate artifact from autoscaling input.
  Operators need to see saturation early; an alarm that scales the ASG is
  a downstream consumer of the same signal but not the same artifact.
- No new ADR ships from this preflight. A follow-up implementation issue
  that introduces a new alarm, metric emitter, or scaling-policy
  abstraction adds or updates an ADR at that time.

## Current State

### Scaling

- ASG CPU alarms: `aws_cloudwatch_metric_alarm.cpu_high` and `cpu_low` at
  `platform/terraform/modules/portal/ec2/main.tf:573-615`. Namespace
  `AWS/EC2`, metric `CPUUtilization`, statistic `Average`, period 120 s,
  `evaluation_periods = 2`, thresholds wired from `var.scale_up_threshold`
  / `var.scale_down_threshold` (currently 70/30 in both dev and prod
  tfvars).
- ASG sizing: `asg_min_size`, `asg_max_size`, `asg_desired_capacity` set
  per environment. dev: 1/1/1, prod: 2/5/2
  (`platform/terraform/environments/{dev,prod}/portal/terraform.tfvars`).
- ASG health probe source: `health_check_type = "ELB"`,
  `health_check_grace_period = 900` at
  `platform/terraform/modules/portal/ec2/main.tf:514-515`. Termination
  decisions chain off the ALB target-group health check.
- Scaling policies: `aws_autoscaling_policy.scale_up` /
  `scale_down`, simple `ChangeInCapacity` of +/-1 with a 300 s cooldown
  (`platform/terraform/modules/portal/ec2/main.tf:553-571`). No
  target-tracking, no step-scaling, no predictive scaling.

### Health

- ALB target group: `aws_lb_target_group.this` at
  `platform/terraform/modules/portal/alb/main.tf:127-156`. Health check
  `path = var.health_check_path` (`/health` in dev/prod tfvars), protocol
  HTTP, matcher `200`, `interval = 30`, `healthy_threshold = 2`,
  `unhealthy_threshold = 3`, `timeout = 5`. Stickiness conditional on
  `var.enable_stickiness`.
- App middleware: `HealthCheckMiddleware` at
  `shifter/shifter_platform/config/middleware.py:36-51`
  short-circuits `/health` and `/health/` to a plain-text `OK` response,
  bypassing `django-health-check`. The DB/cache/storage probes from
  `django-health-check` are installed
  (`shifter/shifter_platform/config/settings.py`) but never reached on
  these paths. The same `/health` path is reused as the container-level
  `HEALTHCHECK` in `shifter/shifter_platform/Dockerfile:62`.
- This behavior is fully tracked by #477 and is not redesigned here.

### Runtime

- Portal serves both HTTP and WebSocket through a single Daphne process
  at `shifter/shifter_platform/entrypoint.sh:171-182`. Daphne is the
  default `CMD`; `gunicorn` is co-installed but not invoked. Per-process
  saturation is the dominant failure mode this preflight reasons about,
  but choice of process model is owned by #174.
- Browser SSH terminals consume per-session websocket FDs, asyncssh
  sockets, and event-loop work inside the same Daphne process. Capacity
  caps land on `TERMINAL_MAX_SESSIONS` etc. in `config/settings.py`.
- Guacamole RDP/SSH URL bootstrap runs through the same portal request
  path; saturation there is observed as inconsistent RDP/Guacamole
  access. The bootstrap blocking call is owned by #848.

### Adjacent telemetry already collected

- Redis: CPU, memory, connections alarms at
  `platform/terraform/modules/portal/redis/main.tf:169-`. Channel-layer
  pressure shows up here first.
- SQS: queue depth (`ApproximateNumberOfMessagesVisible`), message age
  (`ApproximateAgeOfOldestMessage`), DLQ depth at
  `platform/terraform/modules/portal/messaging/main.tf:99-171`. Backend
  worker backlog is visible here.
- Engine provisioner: range launch failure and subnet exhaustion alarms
  at `platform/terraform/modules/engine-provisioner/alarms.tf`.
- Guacamole ECS: `TargetTrackingScaling` on
  `ECSServiceAverageCPUUtilization` at
  `platform/terraform/modules/guacamole/ecs.tf:267-`. The Guacamole layer
  already uses target tracking; the portal ASG does not.
- ALB-level metrics (`TargetResponseTime`,
  `HTTPCode_Target_5XX_Count`, `RequestCount`,
  `ActiveConnectionCount`, `RejectedConnectionCount`) are emitted by AWS
  automatically but have no Terraform-managed alarms today.
- Application-side metric emission is absent: no Prometheus, statsd,
  CloudWatch `PutMetricData`, or custom emitter in
  `shifter/shifter_platform`.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #851 |
| --- | --- | --- |
| Portal IaC topology | `platform/terraform/modules/portal/{ec2,alb,redis,messaging,ssm}`, environment roots under `platform/terraform/environments/*/portal` | Any new alarm, target-tracking policy, or stickiness change lives in these modules; no parallel module. |
| Health probe wiring | `platform/terraform/modules/portal/alb/main.tf` target group, `shifter/shifter_platform/config/middleware.py`, `shifter/shifter_platform/config/urls.py`, `django-health-check`, `shifter/shifter_platform/Dockerfile` HEALTHCHECK | Any redesign goes through #477; #851 records gaps but does not change probe shape. |
| ASGI runtime | `shifter/shifter_platform/entrypoint.sh`, `shifter/shifter_platform/config/{asgi,_channels,settings}.py` | #851 reasons about per-process saturation; runtime swap is #174's contract. |
| Channels/Redis | `config/_channels.py`, `config/settings.py`, `entrypoint.sh`, `scripts/gcp/render_runtime_env.py` | Channel-layer backlog is a saturation signal; reuse the channel-layer env contract. |
| Observability / logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value` | Any new logger line proposed in a follow-up reuses ECS JSON formatting and sanitization helpers. |
| CloudWatch alarm patterns | Redis CPU/memory/connections alarms, SQS queue-depth/message-age/DLQ alarms, engine-provisioner alarms | Match shape (`evaluation_periods`, `period`, dimensions, `alarm_actions`) when proposing new portal-side alarms; do not invent a parallel alarm DSL. |
| Stickiness convention | `var.enable_stickiness` on portal ALB target group | Preserve websocket session affinity; reconnect storms are #847's lens. |
| Cross-cutting auth surface | `config.middleware.HealthCheckMiddleware`, `ALLOWED_HOSTS` posture for health probes | Public health surface stays unauthenticated and coarse; verbose diagnostics go elsewhere. |
| AWS runtime topology | `platform/terraform/modules/portal/{alb,ec2,redis}`, environment roots | Preserve ALB TLS, WAF/admin blocking, EC2 instance profile boundaries. |
| GCP runtime topology | `platform/charts/shifter/templates/*`, `platform/k8s/gcp/base/**` | Any portal probe or scaling reshape carries through both providers, not just AWS. |
| Enforcement | `.importlinter`, `.tflint.hcl`, `.kube-linter.yaml`, ADR guard | No guardrail weakening to ease alarm or probe changes. |

## Symptom to Signal Matrix

Reported live-event symptoms (from #846):

- A. Portal/Django CPU pinned under low-to-moderate user count.
- B. Websocket terminal connections dropped.
- C. RDP/Guacamole access inconsistent.
- D. Health and capacity reads "fine" while users see failures.

Candidate signals, with current availability:

| Signal | Source | Availability today | Maps to symptom |
| --- | --- | --- | --- |
| EC2 `CPUUtilization` average | `AWS/EC2`, in use | wired (`cpu_high`/`cpu_low`) | A (lagging, instance-wide) |
| Per-process / per-container CPU | none | needs emitter | A (leading on single-process saturation) |
| ALB `TargetResponseTime` p95/p99 | `AWS/ApplicationELB` | emitted, no alarm | A, D |
| ALB `HTTPCode_Target_5XX_Count` | `AWS/ApplicationELB` | emitted, no alarm | A, D |
| ALB `HTTPCode_ELB_5XX_Count` | `AWS/ApplicationELB` | emitted, no alarm | A, D (load balancer side failures) |
| ALB `RequestCount` and `RequestCountPerTarget` | `AWS/ApplicationELB` | emitted, no alarm | A, D (input volume) |
| ALB `ActiveConnectionCount` / `RejectedConnectionCount` | `AWS/ApplicationELB` | emitted, no alarm | A, B (admission saturation) |
| ALB `TargetConnectionErrorCount` | `AWS/ApplicationELB` | emitted, no alarm | A, B |
| ALB target health (`UnHealthyHostCount`) | `AWS/ApplicationELB` | emitted, no alarm | C, D |
| Daphne / event-loop lag | none | needs emitter (e.g. periodic loop heartbeat or asyncio task latency probe) | A, B |
| Channels-redis group length / pending | Redis, derivable via INFO/`channel_layer.receive` instrumentation | needs emitter | B |
| Redis CPU / memory / connections | already alarmed (`modules/portal/redis`) | wired | B (downstream of channel layer load) |
| SQS queue depth / message age / DLQ | already alarmed (`modules/portal/messaging`) | wired | A, D (deferred work backlog) |
| Guacamole bootstrap latency / failure rate | none | needs emitter (covered conceptually by #848) | C |
| WebSocket close code distribution | none | needs emitter (covered conceptually by #847) | B |
| Per-process FD count, socket count | none | needs emitter | A, B |
| `TERMINAL_MAX_SESSIONS` cap utilization | `TERMINAL_*` env settings, counted in process | needs emitter (covered conceptually by #847) | A, B |
| Container HEALTHCHECK pass rate | `shifter/shifter_platform/Dockerfile:62` | emitted to Docker; not surfaced as a metric | D |

The matrix does not pick a winner. It constrains the evidence each
follow-up issue must collect before choosing a scaling input, a health
probe redesign, or a new emitter. The point of separating health from
scaling is that the same signal may inform both decisions, but each
decision has its own threshold and failure mode.

## Cross-Cutting Layers

- Auth surface: the ALB health probe path is public, hits the portal as
  ALB-IP-as-Host, and bypasses `ALLOWED_HOSTS` by design (see
  `HealthCheckMiddleware`). Anything #851 follow-up changes about that
  surface must preserve the "coarse, unauthenticated, non-sensitive"
  property. Verbose diagnostics belong on an authenticated admin
  surface, in CloudWatch, or in logs, not on `/health` or any new public
  endpoint.
- Secret-handling: DB, app, Cognito, Guacamole, Redis, and DC secrets
  are loaded by `entrypoint.sh` through `fetch_runtime_secret` and
  Secrets Manager. Any new diagnostic must not log or label metrics
  with secret values, signed Guacamole URLs, Redis auth URLs, private
  SSH keys, DB error strings containing credentials, or full process
  environments.
- Env-binding shape: new knobs (scaling thresholds, alarm periods,
  metric publish intervals) bind through Terraform variables, env
  tfvars, SSM/user-data hydration, Django settings via `_env_int` and
  friends, and the GCP renderers in `scripts/gcp/render_runtime_env.py`
  and `platform/charts/shifter`. The seam is parameterized, not
  hard-coded.
- Config validators: Terraform changes must satisfy TFLint and ADR
  guard; Python platform changes must satisfy ruff and import-linter;
  workflow changes must satisfy actionlint; Kubernetes probe changes
  must satisfy kube-linter and kubeconform.
- OS/runtime exposure: saturation evidence must include process CPU,
  instance CPU, FD/socket counts, asyncio event-loop lag, Daphne
  receive/send latency, Redis connection counts, websocket close-code
  distribution, terminal session counts, Guacamole bootstrap latency.
  Do not collect this by dumping argv, env, or full request bodies.
- Error envelopes: any HTTP-side change reuses `shared.errors` user-
  message classifiers; log lines reuse `ECSFormatter` plus
  `safe_log_value`. No raw exception text to clients; no per-keystroke
  audit.
- WAF interaction: rate-based blocks and managed-rule actions in
  `modules/portal/alb/main.tf` already shape request volume reaching
  the targets. Saturation analysis must not double-count WAF blocks as
  app load, and must not propose disabling WAF to ease load tests.

## Extensibility Seam

The seam is a portal capacity-signal contract with two cells:

- Health/readiness role: which dependencies must answer for a target to
  remain in service. Today: TCP socket and Django ASGI worker can write
  `OK`. Owned by #477.
- Scaling input role: which metric (and statistic, period, threshold,
  evaluation policy) controls ASG capacity. Today: EC2 `CPUUtilization`
  average, 70/30, 120 s, 2 evaluation periods, simple step.

Keep the seam parameterized so a follow-up that selects ALB
`TargetResponseTime` as the scaling input or per-process CPU as a
custom metric changes a Terraform variable or a metric source, not the
shape of `aws_autoscaling_policy.scale_up` or the entire alarm block.

## Evidence Bar

A follow-up implementation issue that changes a portal scaling input,
health probe, or runtime topology should land with at least:

- An event-shaped load test or captured production trace that records,
  per minute: EC2 CPU per instance, ALB `TargetResponseTime` p95/p99,
  ALB `HTTPCode_Target_5XX_Count`, ALB `RejectedConnectionCount`, ALB
  `ActiveConnectionCount`, Daphne process CPU, FD/socket count,
  channel-layer Redis CPU and connection count, websocket close-code
  distribution, Guacamole bootstrap latency, and SQS queue depth.
- A timeline correlating user-visible failures (HTTP 5xx,
  websocket close codes for non-client reasons, RDP bootstrap failures)
  with each candidate scaling signal, identifying which signal moved
  first.
- A statement of false-positive risk: how often the candidate signal
  trips under normal warm-ups, deploys, and instance refreshes.
- A statement of target-churn risk if the candidate signal is also used
  for ALB target health. If the same signal can fail health, the
  proposal must explain how it avoids removing targets that are
  overloaded-but-live.
- A statement of secret-handling risk: any signal that surfaces request
  paths, query strings, or response bodies must show that signed
  Guacamole URLs, Redis auth URLs, and other secret-bearing strings
  cannot leak.

Pure "raise the threshold" or "raise ASG max" proposals without this
evidence are rejected by the contract this preflight is establishing.

## Gotchas

- EC2 average CPU lags single-process Daphne saturation because the
  portal underutilizes instance cores in the current single-process
  posture; raising the alarm threshold or `asg_max_size` without
  attributing the bottleneck repeats the documented event-time pattern.
- Stickiness is on for websocket affinity. Any scaling proposal that
  shortens connection lifetimes (faster instance refresh, aggressive
  scale-in) must explain reconnect amplification, not only user-session
  count.
- ALB health check at 30 s interval with `unhealthy_threshold = 3` and
  `timeout = 5` already tolerates a noisy minute; reducing those values
  to surface saturation faster is the target-churn risk the design
  decisions section calls out.
- Container `HEALTHCHECK` and ALB health check both hit the same
  `/health` path; changing one without the other splits the truth
  source (issue #477).
- `django-health-check` is installed but unreached for the ALB path,
  so adding new probes there has zero deployment cost until middleware
  routing changes (issue #477's contract).
- Guacamole RDP path failures may be observed as portal saturation
  through the bootstrap call (#848); attribution must distinguish
  Guacamole-side capacity from portal request-path capacity.
- `TargetTrackingScaling` is already used for the Guacamole ECS
  service; following the same pattern on the portal ASG is
  straightforward but not pre-committed by this preflight.
- A new app-side metric emitter (Prometheus, statsd, or
  CloudWatch `PutMetricData`) is a cross-cutting concern; do not adopt
  one without explicit ADR work.

## Anti-Patterns

- Encoding overload, dependency health, and process liveness into a
  single `/health` response and reading the resulting binary as the
  scaling signal.
- Treating EC2 average CPU as equivalent to Python process saturation,
  channel-layer backlog, Guacamole bootstrap readiness, SQS backlog,
  or websocket capacity.
- Lowering ALB health thresholds to surface overload faster, causing
  target churn instead of scaling.
- Raising `asg_max_size`, ALB timeout, or stickiness duration in lieu
  of attributing the bottleneck.
- Introducing a new repo-wide metrics framework, DTO, exception
  hierarchy, validation schema, or logging format before evidence
  proves one is required.
- Logging signed Guacamole URLs, Redis auth URLs, DB credentials, or
  raw exception text to make capacity analysis easier.
- Weakening WAF, `AllowedHostsOriginValidator`, ALB admin blocking,
  ADR guard, TFLint, actionlint, import-linter, kube-linter, or
  kubeconform to ease load testing.
- Scoping a follow-up implementation issue without evidence that
  satisfies the evidence bar above.

## Non-Goals

- No implementation, alarm change, scaling-policy change, threshold
  change, ALB health-check change, middleware change, runtime split,
  or new framework ships in #851.
- No `/health` redesign (owned by #477).
- No Daphne / Gunicorn / Uvicorn runtime swap (owned by #174).
- No terminal websocket capacity envelope (owned by #847).
- No Guacamole bootstrap path change (owned by #848).
- No Channels-Redis posture change (owned by #849).
- No new Ground Control requirement is attached; the issue body is the
  source of truth for acceptance.

## Follow-up Tracks

The following implementation issues become file-able once their
evidence bar is met. Each should be opened with a link back to #851 and
to the raw measurement artifact that supports it:

- Portal autoscaling input selection: candidates include ALB
  `TargetResponseTime` target tracking, ALB `RequestCountPerTarget`
  target tracking, or a custom per-process CPU metric. Evidence must
  show which signal moves first relative to user-visible failure.
- Portal ALB health surface separation from autoscaling signal: ensure
  the health probe does not fail under transient overload. Cross-link
  to #477's `/health` redesign.
- Per-process / per-container CPU emitter: only if the autoscaling
  selection above requires it. Decide between Prometheus, statsd, or
  CloudWatch `PutMetricData` at that time, not in this preflight.
- WebSocket / overload observability surface: counts and latencies
  visible to oncall before users see drops. Cross-link to #174 and
  #847.
- ALB-side alarm coverage: managed alarms for
  `TargetResponseTime`, `HTTPCode_Target_5XX_Count`,
  `RejectedConnectionCount`, `UnHealthyHostCount` with thresholds
  derived from event-time evidence.

Each follow-up's `/implement` preflight will read this document, and the
follow-up's plan must explain how its proposed change satisfies the
evidence bar above without violating the architecture decisions and
cross-cutting constraints recorded here.
