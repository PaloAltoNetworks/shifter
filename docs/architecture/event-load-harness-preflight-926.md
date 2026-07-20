# Event Load Harness Preflight (#926)

Status: pre-implementation guidance

Date: 2026-06-14

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/926>

## Scope Boundary

Issue #926 is a verification-stack change. The shipping contract is a scripted,
repeatable harness that runs against a deployed development environment and
produces an event baseline envelope: portal/process shape, Redis and RDS
posture, Guacamole task shape, observed latency/error/drop metrics, and a
supported concurrency statement with margin.

The harness is not a portal redesign, a new observability platform, a new CTF
scoring model, or a substitute for deployment guardrails. It should exercise
the real user paths that failed or were under-measured during the May event:
authenticated page traffic, browser terminal websockets, Guacamole RDP
bootstrap and service path, range-status polling, and optional native CTF
submission/scoreboard load.

Keep these concerns separate in design and output:

1. Load generation: authenticated virtual users and profile mix.
2. System metrics collection: provider/app/platform signals for the same time
   window.
3. Report rendering: a sanitized, reproducible envelope document.
4. Environment sizing decisions: a conclusion based on evidence, not encoded
   as Terraform or Kubernetes changes in this issue.

## Architecture Decisions

- Prefer a harness location under `uat/` for event-shaped live-environment
  validation. A thin `scripts/` wrapper is acceptable only if it delegates to
  the harness and keeps the one-command operator experience.
- The one command must orchestrate load, metrics collection, and report render.
  It may call smaller modules internally, but the operator-facing contract is a
  single bounded run against one explicit target environment.
- Drive real HTTP/websocket/browser-session contracts. Do not write direct
  database rows, call Django services in-process, inject ASGI scopes, or mock
  Guacamole/terminal/CTF services to satisfy load profiles.
- Treat CTFd and native Django CTF as different systems. CTFd load may reuse
  the standalone CTFd client conventions in `scripts/ctfd-workshop`; the
  optional native scoring profile must exercise Shifter's `/ctf/` HTTP/API
  paths and `ctf.services` behavior through the app, not through CTFd APIs.
- Reuse provider-native telemetry first: AWS ALB/EC2/ElastiCache/RDS/ECS and
  GCP pod/container/service metrics. Do not introduce Prometheus, statsd,
  CloudWatch `PutMetricData`, a public diagnostics endpoint, or a durable
  measurement schema unless a later evidence-backed issue accepts that new
  cross-cutting surface.
- If a requested metric is unavailable exactly, name the proxy honestly. For
  example, derive a RDS connection-rate proxy from provider connection samples
  only if the report labels it as a derivative/proxy; do not call SQS backlog
  or Redis connections a "web worker busy ratio."
- Generated reports are evidence artifacts. They may be committed only after
  sanitization. Raw run logs, cookies, tokens, Guacamole URLs, terminal
  streams, and credential manifests must not be committed.
- No new ADR is required for the harness itself. Add an ADR/design decision
  only if the implementation introduces a new metrics framework, public
  diagnostic surface, runtime topology, repo-wide report schema, or deployment
  control loop.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #926 |
| --- | --- | --- |
| Existing event lessons | `scenario-dev/polaris/lessons-4.md` | Use the May event symptoms and preflight checklist as scenario input; do not treat small range provisioning as event load evidence. |
| Terminal capacity boundary | `docs/architecture/terminal-websocket-capacity-preflight-847.md`, `terminal-websocket-capacity-847.md`, `mission_control.consumers.SSHConsumer`, `mission_control.terminal_sessions` | Measure per-process terminal caps, close codes, reconnect amplification, FD/socket pressure, and portal HTTP impact. Do not route terminal bytes through Redis or shared notifications. |
| Portal health/scaling evidence | `docs/architecture/portal-health-scaling-preflight-851.md`, `portal-health-readiness-preflight-477.md`, `config.health`, AWS ALB target group health, GCP probes | Keep readiness, overload, and autoscaling signals separate in the report. Do not make `/health` the load result. |
| Channel-layer posture | `docs/architecture/portal-channel-layer-backend.md`, `config/_channels.py`, `config/asgi.py` startup posture log | Report the active `CHANNEL_LAYER_BACKEND` and Redis provider metrics. Do not infer Redis use from ASG mode. |
| ASGI real-stack evidence | `docs/architecture/asgi-render-integration-preflight-924.md`, `config/asgi.py`, `mission_control/routing.py`, `shared/routing.py` | Load tests should satisfy host/origin/session gates instead of bypassing ASGI middleware or consumers. |
| Portal web runtime | `docs/architecture/portal-asgi-process-manager-preflight-174.md`, `entrypoint.sh`, `TERMINAL_*` settings | Report process model, worker count when present, per-process terminal caps, FD limits, CPU, and memory. More workers multiply process-local caps. |
| Guacamole access broker | `docs/architecture/guacamole-first-click-rdp-preflight-395.md`, `mission_control.views._guacamole`, `mission_control.guacamole`, `_guacamole_bootstrap` | Exercise the JSON-auth bootstrap endpoint and Guacamole service path; never log signed URLs or tokens. |
| Range/status access | `ctf.views.participant_range`, `ctf.views.api_range_status`, `ctf.services.range`, `mission_control.consumers.RangeStatusConsumer` | Poll and websocket paths should use normal participant sessions and existing CMS/CTF status services. |
| Native CTF scoring | `docs/design/ctf-hint-penalty-scoring-preflight-519.md`, `ctf.services.submission`, `ctf.services.scoring`, `ctf.views.api_submit_flag`, `ctf.views.api_scoreboard` | Submission flood and scoreboard polling must use the native CTF HTTP/API contract; no duplicate scoring engine or direct aggregate SQL. |
| Standalone CTFd ops | `scripts/ctfd-workshop/common.py`, `ctfd_reconcile.py`, `sync_polaris_ctfd.py`, `create_users.py`, `scripts/ctfd-workshop/README.md` | Reuse CTFd base-url/token/env conventions and post-sync/readback discipline where CTFd is in scope; do not reuse CTFd client code for native CTF. |
| Script shape | `scripts/check_rds_pending_modifications/check_rds_pending_modifications.py`, `scripts/gcp/render_runtime_env.py`, script-local `pyproject.toml` patterns | Use `argparse`, bounded polling, fixed-argv subprocess calls, explicit validation, redaction, and narrow optional dependencies. |
| Runtime env and secrets | `config.settings` `_env_*`, `scripts/gcp/render_runtime_env.py`, `entrypoint.sh`, `docs/architecture/gcp-runtime-secret-env-preflight-1195.md` | Keep load-test config separate from app runtime config; do not add app env knobs just to drive the harness. |
| Logging/error hygiene | `config.logging.ECSFormatter`, `shared.log_sanitize`, `shared.errors.classify_user_message`, `ctf.exceptions` | Logs and reports use sanitized IDs, aggregate counts, and authored error classes. Do not publish raw exception text or raw API bodies. |
| Provider runtime topology | AWS `platform/terraform/modules/portal/{alb,ec2,redis,messaging}`, `platform/terraform/modules/guacamole`, GCP `platform/k8s/gcp/base/**`, `platform/charts/shifter/**` | Metrics and envelope fields should name the actual deployed shape: instance/pod count, worker/process count, Redis/RDS/Guacamole shape. |
| Enforcement | `.ground-control.yaml`, `.gc/plan-rules.md`, ADR guard, import-linter, TFLint, actionlint, kube-linter, kubeconform | The harness must not weaken CI or deployment checks. Run the stack-native validators for any touched surface. |

## Cross-Cutting Layers

- Auth surface: portal HTTP uses Django sessions, OIDC/Identity Platform, magic
  links, or development login depending on environment. Websockets use
  `AllowedHostsOriginValidator` plus `AuthMiddlewareStack`. Native CTF APIs use
  `@login_required`, `ctf_participant_required` / role gates, CSRF where
  applicable, and event-scoped participant checks. The harness must obtain and
  replay real sessions/cookies instead of adding test-only auth bypasses.
- Development auth: `config.dev_auth.dev_login` is allowed only in DEBUG or
  `ENVIRONMENT=development` and only over local/admin access paths. A harness
  may use it for deployed dev through the documented access path, but must not
  broaden `DEV_LOGIN_ALLOWED_*`, make it work in prod, or describe it as an
  event auth model.
- CTFd auth: standalone CTFd admin setup may use `CTFD_TOKEN` and the existing
  `CtfdClient` pattern. Participant traffic should use participant credentials
  or sessions. Admin tokens must not be used as participant load.
- Secret-handling surface: participant passwords, magic-link invite tokens,
  CTFd admin tokens, Django session cookies, CSRF tokens, Guacamole auth
  tokens/URLs, Redis AUTH material, DB credentials, SSH private keys, and cloud
  credentials are secret-bearing. Keep them out of argv, logs, report markdown,
  screenshots, generated JSON, GitHub comments, and artifacts. Prefer env or a
  gitignored 0600 credential manifest over CLI token/password arguments.
- Config shape: the harness needs its own run config for target URL,
  environment label, profile mix, concurrency, ramp, duration, participant
  source, metric source, provider/region/project, and report path. That config
  is not a Django settings schema, CTF DTO, Terraform variable, or Kubernetes
  value. Validate it at startup and fail before generating load.
- URL/host validation: target URLs must be explicit, parseable `https://` URLs
  unless a local/SSM tunnel profile explicitly allows `http://localhost`.
  Websocket `Host` and `Origin` headers must satisfy the deployed app's allowed
  host/origin policy. Do not relax `ALLOWED_HOSTS`, WAF, Cloudflare, or ingress
  policy to make load generation easier.
- OS/process exposure: secrets in argv are visible to other same-host process
  readers; full request URLs can leak in shell history and process listings.
  The harness should pass only non-secret file paths, profile names,
  concurrency values, and output paths on argv. It must also account for portal
  process CPU, memory, DB connections, Redis connections, websocket FDs, SSH
  sockets, Guacamole connections, and client-side socket exhaustion.
- Error envelopes: HTTP failures should be aggregated by status code, route
  class, and authored application error category. Websocket failures should be
  counted by `shared.enums.WebSocketCloseCode`. Do not copy raw CTF flag
  submission bodies, Guacamole bootstrap response bodies, exception strings, or
  terminal output into the report.
- Logging and observability: use existing ECS JSON app logs and provider
  metrics as inputs. Load-client logs should be structured but sanitized, with
  low-cardinality labels such as profile, route class, participant index, close
  code, and status code. Do not introduce a second app logging formatter.
- Persistence: the harness should write local run artifacts and a final report.
  It should not add Django models, migrations, repositories, audit tables, CTF
  scoring tables, Redis keys for measurement, or a durable telemetry store in
  the app.
- Network safety: the issue targets deployed dev. The harness must require an
  explicit target and make production or unknown hosts an intentional refusal
  unless a separate operator gate exists. Do not disable WAF, Cloudflare
  controls, NetworkPolicies, security groups, or TLS verification to get a
  cleaner run.
- Workflow surface: if a workflow is added later, it must not run load from
  pull_request, must not expose deploy credentials to untrusted code, and must
  follow the trusted push/workflow_dispatch environment gating in ADR-003-R5.

## Whole-Repo Scope

Surfaces likely in scope for implementation:

- `uat/**` for the harness, profiles, report template, and operator notes.
- `scripts/**` only for a thin entrypoint or shared script-local package if
  needed for the one-command contract.
- `scripts/ctfd-workshop/**` only if CTFd setup/load reuses the existing client
  helpers; keep standalone CTFd separate from native CTF.
- `shifter/shifter_platform/ctf/**`, `mission_control/**`, `engine/services/**`,
  `shared/**`, and `config/**` as route/contract references. Do not change them
  unless the harness exposes a real bug that a separate implementation accepts.
- AWS topology and metrics sources in `platform/terraform/modules/portal/**`,
  `platform/terraform/modules/guacamole/**`, and environment roots.
- GCP topology and metrics sources in `platform/k8s/gcp/base/**`,
  `platform/charts/shifter/**`, `scripts/gcp/**`, and GCP Terraform outputs.
- CI/workflows only if a later change intentionally adds a manual load-runner
  workflow. That is guardrail work and must pass actionlint and ADR guard.

Out-of-scope for this harness issue unless separately accepted:

- Changing portal autoscaling policy, RDS/Redis/Guacamole sizing, Gunicorn
  worker counts, terminal limits, health checks, WAF policy, NetworkPolicies, or
  Terraform defaults.
- Adding app-side metrics emitters, public diagnostics, new auth exchanges, new
  service abstractions, or new schemas in the Django app.

## Extensibility Seam

The durable seam is a profile plus metrics-adapter contract:

- profile: named traffic mix, target concurrency, ramp, duration, and optional
  native-CTF-scoring variant;
- actor source: participant credential/session manifest, CTFd participant CSV,
  or dev-login actor generator for deployed dev only;
- route catalog: page views, terminal websocket actions, Guacamole bootstrap,
  range-status polling/websocket, CTFd scoring, native CTF submission and
  scoreboard polling;
- metrics adapter: AWS, GCP, or "client-only" with explicit gaps;
- report renderer: a stable sanitized envelope with raw metric provenance,
  environment shape, run parameters, p95/p99 latency, error/drop counts, and a
  supported-concurrency conclusion.

The next reasonable variation is changing the event mix from 200 to 500
participants, switching provider from AWS dev to GCP dev, or adding a new route
class such as notifications. That should be a profile/config change, not a
rewrite of auth handling, metric collection, report format, or app services.

## Evidence Bar

The report must include, at minimum:

- target environment: URL, provider, region/project, git SHA or image digest if
  available, run start/end time, profile name, target concurrency, ramp, and
  duration;
- deployment shape: portal instance/pod count, process/worker model, terminal
  caps, Redis backend posture, RDS class/storage/Multi-AZ posture, Guacamole
  guacd and guacamole-client desired/running task or replica count;
- client results: per-route request counts, success/error counts, p50/p95/p99
  latency, websocket open/drop/close-code counts, reconnect attempts, and
  Guacamole first-attempt success rate;
- provider metrics for the same time window: portal CPU, memory where
  available, ALB/ingress latency and 5xx, active/rejected connections, RDS
  connections and CPU, Redis CPU/memory/connections, Guacamole ECS/pod CPU and
  task/replica health, SQS backlog if worker paths are touched;
- attribution: which signal moved first before user-visible failure, and which
  resource bounded the supported concurrency;
- conclusion: supported concurrency with explicit margin, the limiting factor,
  and sizing implications for #910. If evidence is incomplete, the report must
  say which metric is missing rather than filling the gap with a guess.

## Gotchas

- Terminal session caps are process-local. A future Gunicorn worker count
  multiplies capacity and resource usage; the report must state process count,
  not just pod/instance count.
- Terminal reconnect behavior amplifies load after drops. Count reconnects and
  close codes, not just original virtual users.
- Guacamole has at least three distinct surfaces: portal bootstrap, guacamole
  client, and guacd/RDP backend. A failure in one must not be attributed to the
  others without evidence.
- Full Guacamole URLs contain tokens. Treat them like credentials.
- CTFd APIs and native CTF APIs have different auth, schema, scoring, and
  persistence models. Do not combine their metrics into one "CTF scoring"
  bucket without labels.
- Native CTF scoreboard queries can be expensive because they aggregate
  submissions and awards. Measure scoreboard polling separately from submission
  writes so read pressure and write pressure are not conflated.
- Some native CTF error responses currently include `str(CTFError)`. The
  harness should aggregate and sanitize errors instead of republishing raw
  bodies.
- DB "connections opened/sec" may not be directly available from provider
  metrics. Use direct database introspection only with an explicitly scoped,
  read-only operational credential and never store DSNs or credentials in the
  report; otherwise report provider connection-count derivatives as proxies.
- Redis channel-layer metrics are not terminal byte-stream metrics. Terminal
  bytes should not hit Redis.
- WAF, Cloudflare, and bot protections can be the first limiter. The report
  should separate edge blocks/challenges from application failures and should
  not recommend disabling protection as a fix.
- Load generation from the operator machine can become the bottleneck. Record
  client CPU, open sockets, DNS errors, and local file descriptor limits so
  client exhaustion is not mistaken for portal saturation.

## Anti-Patterns

- A load script that logs in once as an admin and sends every request with the
  same session.
- Directly importing Django models/services from the harness to create scores,
  ranges, sessions, or status rows.
- Creating duplicate request DTOs, CTF scoring schemas, terminal protocols,
  Guacamole token brokers, cloud secret adapters, exception hierarchies, or log
  formats.
- Using process-level `ssh`, `redis-cli`, `psql`, or shell pipelines with
  credentials in argv or temp files to make collection easier.
- Treating `/health` success, EC2 average CPU alone, or "no 500s" as the event
  envelope.
- Reporting a single average latency instead of per-route p95/p99 and error
  distribution.
- Hiding missing metrics, stale Terraform applies, RDS pending modifications,
  Redis in-memory posture, or Guacamole task under-count behind a green summary.
- Weakening CI, WAF, TLS, `AllowedHostsOriginValidator`, CSRF, NetworkPolicies,
  security groups, ADR guard, import-linter, TFLint, actionlint, kube-linter, or
  kubeconform for load-test convenience.

## Non-Goals

- Do not implement the harness in this preflight document.
- Do not resize infrastructure, change autoscaling, or set the #910 baseline
  without a generated envelope report.
- Do not redesign CTFd sync, native CTF scoring, terminal transport,
  Guacamole auth, portal health, ASGI process management, Redis posture, range
  provisioning, or worker/scheduler health.
- Do not add a new Ground Control requirement; issue #926 is the authoritative
  contract for this requirement-free run.
- Do not add a new app database schema, persistent telemetry store, public
  operator dashboard, or general metrics framework.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must also run the stack-native checks for touched
surfaces: script tests/lint for the harness package, shifter-platform Ruff and
import-linter for Python app changes, actionlint for workflows, TFLint for
Terraform, and kube-linter/kubeconform for Kubernetes manifests.
