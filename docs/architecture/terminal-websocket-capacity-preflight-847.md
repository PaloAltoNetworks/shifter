# Terminal WebSocket Capacity Preflight (#847)

Status: pre-implementation guidance

Date: 2026-05-31

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/847>

## Scope Boundary

Issue #847 is diagnostic/design work. The shipping contract is to measure the
browser terminal concurrency envelope, decide from evidence whether terminal
websocket handling needs an independently scalable runtime, record ownership
boundaries, and link any implementation follow-ups with that evidence.

Do not start by moving terminal traffic out of the portal. First produce a
repeatable envelope that shows how terminal sessions affect portal HTTP,
Guacamole URL bootstrap, status websocket paths, database audit writes, Redis,
file descriptors, SSH sockets, CPU, and memory.

## Architecture Decisions

- Browser terminal transport is a workload boundary, not a new domain boundary.
  Any dedicated ASGI service, target group, terminal gateway, or offload worker
  must still use the existing authorization and connection-resolution seams.
- `mission_control.consumers.SSHConsumer` owns websocket transport behavior.
  `engine.services.connect_terminal()` / `get_ssh_connection_info()` own user
  ownership checks, active-range lookup, range readiness checks, instance
  lookup, secret-reference resolution, and `SSHConnection` construction.
- `engine.ssh.SSHConnection` owns SSH client mechanics. Do not replace it with
  shelling out to `ssh`, `tmux`, or `script`; that would expose credentials and
  process state in harder-to-audit OS surfaces.
- Terminal stream bytes are not notification events. Do not route terminal
  input/output through `shared.channels.groups`, Redis channel-layer groups, or
  the shared websocket notification infrastructure from related issue #679.
- Guacamole RDP/SSH URL bootstrap is a separate access path. Measure it as a
  victim of terminal contention, but do not conflate its signed-url workflow
  with browser-terminal websocket streaming.
- If evidence supports isolation, keep the public browser contract path-shaped
  around `/ws/terminal/<instance_uuid>/` unless the follow-up explicitly accepts
  a client migration.
- No final ADR is needed before measurement. If the outcome chooses a new
  independently scalable terminal runtime, add or update an ADR/design note in
  that implementation to lock the runtime ownership and deploy topology.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #847 |
| --- | --- | --- |
| ASGI routing and websocket auth | `config/asgi.py`, `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, `mission_control/routing.py` | Preserve origin/host and session-auth semantics for any terminal route or split runtime. |
| Terminal websocket transport | `mission_control.consumers.SSHConsumer` | Keep transport-only logic here or in a clearly terminal-owned transport module; do not move domain authorization into the consumer. |
| Range/instance authorization | `engine/services/_terminal.py` via `connect_terminal()` and `get_ssh_connection_info()` | Reuse the service seam; no direct `engine.models` queries from Mission Control or a gateway. |
| SSH client mechanics | `engine/ssh.py` `SSHConnection` | Keep private keys in process memory through `asyncssh`; no SSH CLI argv, temp key files, or subprocess wrappers for the bridge. |
| Template payload schemas | `shared.schemas.RangeContext`, `InstanceContext`, `mission_control.context_processors.active_range`, `mission_control.utils.build_connection_urls()` | Reuse the existing template-safe projection and URL builder; do not create a parallel terminal DTO. |
| Frontend terminal protocol | `static/js/terminal.js`, `terminal-init.js`, `templates/mission_control/terminal.html` | Keep message types (`input`, `resize`, `output`) and close-code behavior stable unless the evidence-backed follow-up scopes a client change. |
| Websocket close codes | `shared.enums.WebSocketCloseCode` | Extend shared enum values if needed; do not invent numeric literals in consumers or JS retry policy. |
| Secrets | `engine.secrets`, `shared.cloud.get_secrets_store()`, `entrypoint.sh` | Secret references may cross layers; secret values must stay in memory and out of env files, ConfigMaps, URLs, logs, argv, and artifacts. |
| Audit | `risk_register.services.audit_session_event()` and `AuditLog` | Reuse connect/disconnect/access-denied session audit semantics; do not add per-byte or per-keystroke audit writes. |
| Error envelopes | `shared.errors.classify_user_message()`, websocket close codes | Keep browser-facing failures generic and authored; log details server-side with sanitization. |
| Logging | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value()` | Structured counts and identifiers only; never log terminal input/output, private keys, full Guacamole URLs, or secret-bearing Redis URLs. |
| Channels/Redis config | `config/_channels.py`, `config/settings.py`, `scripts/gcp/render_runtime_env.py`, `entrypoint.sh` | Reuse the existing channel-layer env contract; terminal byte streaming should not become a Redis workload. |
| AWS runtime topology | `platform/terraform/modules/portal/{alb,ec2,redis}`, environment roots under `platform/terraform/environments/*/portal` | Preserve ALB TLS, WAF/admin blocking, target-group stickiness conventions, Redis channel-layer wiring, and SSM/user_data env hydration. |
| GCP runtime topology | `platform/charts/shifter/templates/{web-deployment,web-service,portal-backendconfig,ingress,networkpolicies}.yaml`, `platform/k8s/gcp/base/**` | Any terminal split needs charted service/deployment/network policy/BackendConfig changes rather than ad hoc manifests. |
| Enforcement | `.importlinter`, `.tflint.hcl`, `.kube-linter.yaml`, ADR guard | Do not weaken import contracts, IaC security checks, or guardrail workflows to make isolation easier. |

## Cross-Cutting Layers

- Auth surface: websocket requests currently pass through
  `AllowedHostsOriginValidator` and `AuthMiddlewareStack`; HTTP Guacamole URL
  endpoints use `@login_required`, CSRF, and Django sessions. A split terminal
  runtime must satisfy the same authenticated-session boundary or introduce an
  explicitly documented, short-lived server-side exchange. Do not put long-lived
  bearer tokens in websocket URLs, local storage, logs, or query strings.
- Authorization and validation surface: `engine.services.connect_terminal()`
  validates user ownership, active range, `READY` status, instance UUID
  presence, SSH key reference, host presence, username, and OS/tmux behavior.
  Keep these checks in the engine service boundary; duplicate checks in a
  gateway are at most defense-in-depth and cannot become authoritative.
- Secret-handling surface: `engine.secrets.get_ssh_key()` resolves provider
  secret references through `shared.cloud`. The private key value belongs only
  in process memory inside the portal/terminal runtime and `asyncssh`; it must
  not be serialized into metrics, capacity artifacts, shell commands, tmp files,
  ConfigMaps, Terraform variables, Helm values, or client-visible JSON.
- Env-binding shape: channel-layer Redis config is built by
  `config._channels._build_channel_layers(os.environ)` and GCP secret hydration
  runs in `entrypoint.sh`. If isolation adds terminal runtime settings, keep
  them explicit and environment-owned, for example placement/capacity knobs,
  idle timeout, and max sessions. Do not hide them inside generic app settings
  or copy provider-specific renderers.
- Config validators: architecture-affecting follow-ups must satisfy ADR guard.
  Python app changes must satisfy `ruff` and import-linter; workflow changes
  must satisfy `actionlint`; Terraform changes must satisfy TFLint; Kubernetes
  changes must satisfy kube-linter and kubeconform on rendered deployable
  manifests.
- OS/process exposure: each active browser terminal consumes a websocket file
  descriptor, an SSH TCP socket, `asyncssh` connection/process state, event-loop
  work, and connect/disconnect audit writes. Capacity evidence must account for
  these OS resources. Do not measure only application p95 and ignore FD/socket
  exhaustion.
- Network exposure: AWS portal networking is owned by the portal ALB/EC2/Redis
  modules and range peering rules. GCP ingress and egress are owned by the Helm
  chart and generated NetworkPolicies. A dedicated terminal workload needs
  explicit, least-privilege ingress and egress to target SSH hosts; broad
  `0.0.0.0/0` pod egress or public SSH exposure is not an acceptable shortcut.
- Error-envelope surface: websocket close behavior must continue to use
  `WebSocketCloseCode` for auth, permission, invalid request, not found, server,
  and SSH failure classes. HTTP endpoints must keep authored JSON errors via
  existing user-message classifiers rather than surfacing raw exception text.
- Observability surface: use ECS JSON logs, sanitized identifiers, and aggregate
  measurements. Useful counters include active sessions, connect attempts,
  successful connects, close-code counts, SSH connect latency, SSH receive loop
  exceptions, audit-write latency/failure count, process RSS, CPU, FD count, and
  non-terminal HTTP/Guacamole latency under load.
- Persistence surface: `risk_register` session audit entries are the existing
  durable record. Do not introduce a second terminal-session schema unless the
  evidence proves a product need beyond capacity diagnosis.

## Extensibility Seam

The seam is a terminal runtime placement and capacity contract:

- placement: colocated portal ASGI, dedicated ASGI deployment/target group, or
  a purpose-built terminal gateway
- limit policy: maximum active terminal sessions per process/pod/instance and
  per user/range, plus rejected-session close code/error behavior
- timeout policy: SSH connect timeout, idle timeout, websocket keepalive, and
  load balancer backend timeout
- telemetry contract: aggregate session counts and latency/error buckets

Keep that seam parameterized so the next variation changes runtime placement or
limits without rewriting engine authorization, template projections, frontend
message schemas, or Guacamole URL generation.

## Evidence Bar

The measurement artifact that closes #847 should report, at minimum:

- max sustained browser terminal sessions per portal process/pod/instance before
  terminal drops or portal HTTP p95 regression appear
- per-terminal CPU, memory, file descriptor, socket, and database audit-write
  cost
- portal HTTP latency and error rate under terminal load, including dashboard,
  range-status views, auth/session-backed requests, and Guacamole URL bootstrap
- websocket close-code distribution and attribution across application errors,
  SSH failures, client reconnects, Redis/channel-layer behavior, process
  saturation, and load-balancer idle behavior
- whether the recommended follow-up is measured limits in the existing portal
  pool or independent terminal scaling, with links to the raw evidence

## Gotchas

- `SSHConsumer.connect()` calls sync Django/secret work through `sync_to_async`.
  Under load, threadpool, database, and secret-provider latency can be the
  bottleneck even when the event loop looks healthy.
- `_read_ssh_output()` currently polls `SSHConnection.receive(timeout=0.1)` in
  one task per active session. Idle terminals are not free.
- Browser retry policy attempts up to five reconnects with exponential backoff
  except selected close codes. Load tests must count reconnect amplification,
  not only original user sessions.
- Guacamole path traffic (`/guacamole`) runs through its own client/guacd
  components, but URL generation and auth/session work still hit the portal.
  Measure both the Guacamole service path and the portal bootstrap endpoint.
- AWS ASG mode has target-group stickiness called out as a websocket affinity
  convention. Do not remove or bypass it without evidence and a replacement
  reconnect story.
- GCP NetworkPolicies are default-deny and currently model public ingress,
  Google APIs, DNS, Guacamole-to-guacd, and private service CIDRs. Terminal
  egress to range SSH must be explicit if a Kubernetes terminal workload is
  introduced.
- Full Guacamole URLs contain auth tokens. Treat them as secret-bearing in logs,
  metrics, load-test artifacts, screenshots, and issue comments.
- `SSHConnection` sanitizes tmux session IDs. Preserve that command-shaping
  guard if session naming is moved or reused.

## Anti-Patterns

- Treating "separate service" as the acceptance criterion before measurement.
- Moving ownership/range/status checks into `mission_control`, JavaScript, an
  ingress rule, or a terminal gateway while bypassing `engine.services`.
- Creating duplicate terminal DTOs, validation schemas, exception hierarchies,
  audit tables, log formatters, secret fetchers, or deployment renderers.
- Sending terminal input/output through Redis channel-layer groups or shared
  notification websocket infrastructure.
- Using process-level SSH commands with private keys in argv, environment, or
  temporary files to avoid `asyncssh` work.
- Fixing drops by only increasing portal replicas, Redis size, ALB timeout, or
  client retries without attributing the limiting resource.
- Logging terminal streams, private keys, signed Guacamole URLs, Redis auth
  URLs, or raw exception text to make capacity analysis easier.
- Weakening `AllowedHostsOriginValidator`, session auth, CSRF on HTTP bootstrap
  endpoints, NetworkPolicies, WAF/admin blocking, ADR guard, TFLint, actionlint,
  kube-linter, kubeconform, or import-linter.

## Non-Goals

- No implementation, runtime split, infrastructure change, or client-protocol
  migration in the preflight itself.
- No formal Ground Control requirement is attached; issue #847 is the source of
  truth for acceptance.
- No redesign of Guacamole, CTFd, range provisioning, notification
  infrastructure, queue workers, storage adapters, or cloud provider factories.
- No new authentication system, secret store abstraction, schema registry,
  exception framework, logging framework, or audit framework.
- No decision that browser terminal support must replace Guacamole SSH/RDP or
  that Guacamole access replaces browser terminals.

## Validation

For preflight documentation changes, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must additionally run the stack-native checks for
the surfaces they touch, especially import-linter for Python package-boundary
changes, actionlint for workflow/load-test automation, TFLint for Terraform
runtime topology, and kube-linter/kubeconform for Kubernetes manifests.
