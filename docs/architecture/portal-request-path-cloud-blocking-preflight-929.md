# Portal Request-Path Cloud Blocking Preflight (#929)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/929>

## Scope Boundary

Issue #929 removes the remaining blocking cloud-secret calls from portal
request-sensitive execution paths. The issue is requirement-free; the GitHub
issue is the source of truth.

The change must preserve the existing Portal access-broker contracts while
moving slow cloud dependency work out of Django's shared ASGI sync bridge:

- Guacamole RDP/SSH HTTP views return a pollable bootstrap request quickly.
- Guacamole credential resolution and token exchange run inside the existing
  bounded bootstrap worker path.
- Browser terminal websocket connect uses a terminal-owned sync executor so a
  connect storm cannot consume the request/page-render sync lane.
- Every AWS boto client used on or near request paths has explicit connect/read
  timeouts through a shared adapter-level policy.

This is not a new access product, runtime split, or secret-vault redesign.

## Architecture Decisions

- Treat cloud secret fetches as blocking dependency work. They must not run in
  `guacamole_rdp_url`, `guacamole_ssh_url`, `api_ngfw_ssh_url`, or the default
  thread-sensitive `sync_to_async` lane used by normal Django request handling.
- Keep the asynchronous Guacamole bootstrap contract in
  `mission_control.guacamole_bootstrap`. It already owns bounded workers,
  queue-full behavior, DB connection cleanup, status persistence, TTL, and
  pollable error envelopes. Extend the work captured by the queued callable;
  do not add a second queue/status schema.
- Keep connection authorization and credential resolution in `engine.services`.
  Mission Control may choose when to call the service, but it must not duplicate
  active-range lookup, instance lookup, NGFW ownership checks, host resolution,
  username defaults, or secret-reference parsing.
- Keep provider secret reads behind `engine.secrets` and
  `shared.cloud.get_secrets_store()`. Do not add direct `boto3` or Google Secret
  Manager calls in views, consumers, CTF, templates, or JavaScript.
- Centralize boto timeout policy in the shared AWS adapter layer. Secrets
  Manager, SQS, ECS, and S3 adapters should not each invent different
  timeout/retry constants or raw `boto3.client(...)` shapes for request-adjacent
  code.
- Terminal websocket sync work remains a transport concern around the existing
  engine service and risk-register audit service. A dedicated executor should
  isolate connect/audit/ownership sync work from HTTP page renders without
  creating a duplicate terminal domain service.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #929 |
| --- | --- | --- |
| Guacamole async bootstrap | `mission_control.guacamole_bootstrap.enqueue_guacamole_bootstrap`, `GuacamoleBootstrapRequest`, bootstrap status/open views | Preserve the 202 + polling contract, queue cap, TTL, and persisted sanitized failures. |
| Guacamole HTTP views | `mission_control.views._guacamole` helpers (`_parse_json_body`, `_require_instance_uuid`, `_get_guac_settings`, `_wrap_bootstrap_error`) | Views should parse/authenticate/enqueue only; credential-bearing service calls belong inside the queued callable. |
| Guacamole JSON auth | `mission_control.guacamole` request dataclasses, payload builders, token retry and timeout logic | Keep this module as the JSON-auth broker; do not fetch cloud secrets here. |
| Range/NGFW authorization and connection data | `engine.services.get_rdp_connection_info`, `get_ssh_connection_info`, `connect_terminal`, `connect_ngfw_terminal`, `engine.services._common` resolvers | Reuse these checks; do not query `engine.models` from Mission Control to avoid blocking secrets. Split/refactor within the engine service boundary only if needed. |
| Secret reads | `engine.secrets.get_ssh_key`, `get_rdp_password`, `shared.cloud.get_secrets_store()`, `shared.cloud.*.secrets` | Secret values stay in process memory and never become view DTOs, logs, URLs, env files, argv, or persisted state. |
| Terminal websocket transport | `mission_control.consumers.SSHConsumer`, `mission_control.terminal_sessions`, `engine.ssh.SSHConnection` | Add executor isolation around sync connect/audit work without changing websocket message schema or engine ownership checks. |
| Audit | `risk_register.services.audit_session_event`, `SessionInfo`, `AuditLog` | Preserve connect/disconnect/access-denied audit semantics; do not audit terminal bytes or secret material. |
| Error envelopes | `shared.errors.classify_user_message`, websocket `WebSocketCloseCode`, bootstrap failure status codes | Continue returning authored non-sensitive HTTP errors and close codes; log details server-side with sanitizers. |
| Logging | `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`, ECS JSON logging | Log request IDs, protocol, target IDs, queue/executor outcomes, durations, and aggregate counts only. |
| Runtime config | `config/settings.py` `_env_int` / `_env_bool`, `entrypoint.sh`, AWS SSM/user-data wiring, GCP renderer/chart/Kustomize env surfaces | New timeout/executor knobs, if added, are typed settings and environment-owned. Do not add provider-specific magic constants in call sites. |
| Enforcement | `.importlinter`, `docs/adr/index.yaml`, `scripts/adr_guard/adr_guard.py`, `.gitleaks.toml`, Terraform/Kubernetes linters for touched platform files | Do not weaken import, secret, workflow, Terraform, or Kubernetes guardrails to make isolation easier. |

## Cross-Cutting Layers

- Auth surface: HTTP Guacamole views still use `@login_required`,
  `@require_POST`, CSRF, and `_get_user`. Terminal websockets still pass through
  `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and `SSHConsumer`
  request validation. Moving work to a worker/executor must not remove these
  gates.
- Authorization and validation surface: `engine.services` remains authoritative
  for active range, range `READY` state, instance UUID membership, NGFW
  ownership, host presence, OS/username defaults, and secret-reference
  resolution. If the HTTP response changes from immediate 400 to pollable
  failed bootstrap for invalid targets, the failure must remain user-scoped and
  sanitized through the existing bootstrap status endpoint.
- Secret-handling surface: secret references may flow through engine state and
  service inputs; secret values may only be materialized inside the bootstrap or
  terminal executor thread long enough to build the Guacamole payload or
  `SSHConnection`. Generated Guacamole URLs/tokens are secret-bearing because
  they authorize a connection.
- Cloud adapter surface: AWS Secrets Manager reads go through
  `shared.cloud.aws.secrets.AWSSecretsStore`; request-adjacent AWS clients should
  receive an explicit botocore `Config` with bounded connect/read timeouts.
  Endpoint and region selection remain `CLOUD_REGION` / `AWS_REGION` /
  `AWS_ENDPOINT_URL`; do not create a view-local AWS client factory.
- Config shape: timeout and executor settings, if introduced, should be
  low-cardinality integers parsed once in `config/settings.py` and named by the
  boundary they control, for example cloud-client timeout and terminal connect
  executor capacity. Keep Guacamole bootstrap capacity on
  `GUACAMOLE_BOOTSTRAP_WORKERS`.
- OS/process exposure: private keys, RDP passwords, JSON-auth payloads, tokens,
  signed URLs, session cookies, and Redis/DB credentials must not appear in
  process argv, shell commands, SSM command strings, access logs, metrics labels,
  browser debug logs, screenshots, or test artifacts.
- Error-envelope surface: bootstrap failures persist a bounded message and HTTP
  error status through `GuacamoleBootstrapRequest`. Terminal failures close with
  `WebSocketCloseCode`. Do not surface raw `ClientError`, botocore endpoint
  strings containing account metadata, stack traces, or secret references to
  clients.
- Observability surface: useful signal is non-secret aggregate latency and
  saturation: bootstrap queue full, bootstrap duration, cloud secret fetch
  timeout/failure count, terminal executor queue/rejection count, terminal
  connect latency, audit-write failure count, and page-render/health latency
  while dependencies are stalled.
- Persistence surface: reuse `GuacamoleBootstrapRequest`, `Range` state secret
  references, and `AuditLog`. Do not add durable storage for secret values,
  terminal sessions, Guacamole tokens, or per-connect credential caches unless a
  separate lifecycle/revocation design is accepted.

## Extensibility Seam

The durable seam is a request-path isolation policy:

- cloud client timeout policy: one shared AWS adapter helper/config, with
  provider-neutral settings names and provider-specific application inside the
  adapter;
- Guacamole bootstrap work: protocol, user id, target id, and a worker-side
  resolver callable that can support RDP, range SSH, NGFW SSH, and future VNC
  without view-specific queues;
- terminal sync executor: capacity, timeout, and DB-connection cleanup wrapped
  around the existing `connect_terminal` and audit service calls.

This lets future cloud providers, credential rotation, terminal runtime
extraction, or additional Guacamole protocols reuse the same boundaries without
rewriting Mission Control views, CTF flows, or engine authorization.

## Whole-Repo Scope

In scope for the future implementation:

- Django access path:
  `shifter/shifter_platform/mission_control/views/_guacamole.py`,
  `mission_control/views/_guacamole_bootstrap.py`,
  `mission_control/guacamole_bootstrap.py`, `mission_control/guacamole.py`,
  `mission_control/consumers.py`, and `mission_control/terminal_sessions.py`.
- Engine service boundary:
  `shifter/shifter_platform/engine/services/_terminal.py`,
  `engine/services/_common.py`, `engine/secrets.py`, `engine/ssh.py`, and
  `engine/models.py` accessors.
- Shared cloud adapters:
  `shifter/shifter_platform/shared/cloud/{__init__,types,exceptions}.py`,
  `shared/cloud/aws/{secrets,queue,task_runner,storage}.py`, and GCP secret
  adapter parity where provider-neutral contracts change.
- Runtime settings and deployment binding:
  `shifter/shifter_platform/config/settings.py`, `entrypoint.sh`,
  AWS portal SSM/user-data wiring, `scripts/gcp/render_runtime_env.py`,
  Helm/Kustomize workload env surfaces only if new settings need deployment
  plumbing.
- Tests and evidence:
  Mission Control Guacamole view/bootstrap tests, engine service secret-boundary
  tests, terminal consumer capacity/connect tests, ASGI page-render/health tests
  from the #924 evidence path, and cloud-adapter tests around boto client config.
- Architecture enforcement:
  `.importlinter`, ADR guard, `.gitleaks.toml`, TFLint/actionlint/kube checks
  for any platform files touched.

## Gotchas And Anti-Patterns

- Do not keep calling `get_rdp_connection_info`, `get_ssh_connection_info`, or
  `connect_ngfw_terminal` before enqueueing Guacamole bootstrap; those paths can
  fetch Secrets Manager values.
- Do not solve this by making the views async while leaving blocking SDK calls
  in the default sync bridge. The bottleneck is the blocking dependency in the
  request-sensitive lane, not the Python syntax.
- Do not create a second bootstrap table, terminal service, cloud secret helper,
  request schema, exception hierarchy, audit table, or logging format.
- Do not bypass engine authorization to avoid secret fetches. If a cheaper
  preflight check is needed, keep it inside the engine service boundary and
  ensure the worker repeats authoritative validation before materializing
  credentials.
- Do not make `/health` depend on Secrets Manager as part of this fix. The
  acceptance criterion is that health and page renders stay responsive when
  Secrets Manager stalls.
- Do not use unbounded executors. Queue pressure must reject or fail quickly with
  a retryable/generic response rather than spawning arbitrary threads.
- Do not move private keys into temporary files, `ssh` subprocess argv, tmux
  commands, or shell wrappers. `engine.ssh.SSHConnection` and `asyncssh` remain
  the terminal mechanism.
- Do not cache secret values beyond the range lifetime or outside a bounded
  provider-neutral credential cache. Cache keys must be secret references or
  range/instance identifiers, never secret values; invalidation must align with
  range destruction or credential rotation.
- Do not log generated Guacamole URLs, tokens, encrypted JSON payloads, RDP
  passwords, SSH private keys, raw secret references, terminal input/output, or
  raw botocore exception text in client-facing errors.

## Non-Goals

- No implementation is performed by this preflight.
- Do not redesign Guacamole auth, replace JSON auth, or introduce durable
  Guacamole DB-managed connections.
- Do not redesign browser terminal protocol, CTF participant access, range
  provisioning, guest credential generation, secret rotation, or NGFW ownership.
- Do not introduce a new global terminal runtime, target group, gateway, metrics
  framework, or health endpoint for this issue.
- Do not weaken ADR guard, import-linter, secret scanning, Terraform checks,
  Kubernetes policy checks, CSRF, session auth, or websocket origin validation.

## Validation

At minimum, architecture or `shifter/shifter_platform` changes on this path must
run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups should additionally run the stack-native checks for
touched surfaces:

- `cd shifter/shifter_platform && uv run ruff check . && uv run ruff format --check .`
- `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`
  when imports change.
- Targeted tests proving stalled Secrets Manager does not block `/health` or
  representative authenticated page renders, and that terminal connect storms do
  not serialize against page renders on the same worker.
- Cloud-adapter tests proving every request-adjacent AWS client receives bounded
  botocore timeouts.
- Platform linters (`actionlint`, TFLint, kube-linter, kubeconform`) only when
  workflow, Terraform, or Kubernetes files are touched.
