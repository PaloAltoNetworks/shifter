# Guacamole And Terminal Injectable Ports Preflight (#993)

Status: architecture decision / pre-implementation guidance

Date: 2026-09-03

Issue: GitHub #993, "refactor: put Guacamole and SSH/terminal access behind
injectable ports (mirror shared.cloud)"

This is a requirement-free run. The GitHub issue is the shipping contract. This
note records the boundary decisions and repository-wide guardrails; it is not an
implementation plan.

## Decision

Introduce two narrow injection seams without moving ownership:

1. Keep the Guacamole client port, its concrete JSON-auth HTTP adapter, and its
   `get_guacamole_client(config)` factory in `mission_control`. The factory shape
   mirrors `shared.cloud`, but Guacamole is one provider-agnostic presentation
   gateway, not a cloud capability. It must not be added to `shared.cloud`, the
   installation backend capability registry, or parallel AWS/GCP packages.
2. Reuse `shared.remote_access.TerminalConnection` as the live terminal port.
   Add only a constructor/factory seam at the point where
   `engine.services._terminal` currently instantiates `engine.ssh.SSHConnection`.
   Do not define a second SSH/terminal behavioral protocol or move connection
   authorization into the transport adapter.

The Guacamole client is constructed from one immutable configuration value that
contains the existing public browser base URL, internal API base URL, signing
secret, normalized retry attempts/backoff, and the existing bounded HTTP
timeout. `mission_control.guacamole_session` binds the existing Django settings
once at the application-service edge, obtains the client, and captures that
configured client in the existing bounded bootstrap work. Neither the client
methods nor retry loop may read `django.conf.settings`.

The existing `GuacRDPUrlRequest` and `GuacSSHUrlRequest` remain the per-session
input shapes; configuration fields must move out of those requests rather than
exist in both the request and client configuration. The port exposes the two
real operations (mint RDP URL and mint SSH URL). Do not collapse them into a
generic untyped connection dictionary or confuse the persisted
`GuacamoleBootstrapRequest.Protocol` access kind with a network transport
interface.

The terminal injection point is a factory, not a pre-built mutable connection.
It receives the already-authorized, already-resolved host, port, username,
private key, host public key, and optional tmux session id and returns a fresh
`TerminalConnection`. Production defaults to `engine.ssh.SSHConnection`. An
explicit keyword-only factory dependency is carried through the existing
Mission Control -> CMS workspace authorization -> Engine runtime authorization
call path, so a consumer test can supply a fake without bypassing either
authorization layer. Do not select a fake through Django settings, a dotted
import string, or mutable module-global test state.

No new ADR is needed. ADR-001-R4 already fixes domain ownership and allowed
facades, ADR-005 governs only cloud-provider adapters, and ADR-019 already
requires external-boundary rather than first-party-topology test doubles.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Layer ownership | ADR-001-R4; `docs/architecture/mission-control-runtime-service-boundary-preflight-994.md`; `scripts/check_layer_imports/layer_imports.yaml`; `.importlinter` | Mission Control owns Guacamole/bootstrap and WebSocket delivery; CMS owns workspace authorization; Engine owns realized runtime authorization and live connection construction. Use only public service facades across layers. |
| Guacamole use case | `mission_control.guacamole_session`, `_guacamole_session_builders`, `guacamole`, and `_guacamole_connection_params` | Insert the client below the existing application service. Preserve the closed range-RDP/range-SSH/NGFW-SSH dispatch and the existing RDP/SSH request dataclasses and parameter builders. |
| Guacamole lifecycle/persistence | `mission_control.guacamole_bootstrap`, `GuacamoleBootstrapRequest`, status/open views | Preserve bounded worker admission, off-request execution, TTL, owner-scoped polling, atomic single-use URL consumption/clearing, and bounded pruning. The client port owns no queue or persistence. |
| Terminal behavior | `shared.remote_access.TerminalConnection` | This is the one behavioral protocol (`connect`, `disconnect`, `send`, `receive`, `resize`, `is_connected`, `at_eof`). A constructor callable may be typed beside it if several layers need the type; do not duplicate the behavior contract. |
| SSH adapter | `engine.ssh.SSHConnection`, `PtySettings`, `SSHConnectionError` | Preserve in-memory key import, optional host-key pinning, tmux session-name sanitization, binary PTY behavior, EOF detection, cleanup, and current exception translation. |
| Runtime authorization and projections | `cms.services._range_access`; `engine.services._terminal` and `_common` | Workspace authorization, active owner, READY state, instance/NGFW identity, declared participant channel, realized metadata normalization, and credential-reference checks all run before adapter construction. Do not move or repeat them in a port. |
| Secret resolution | `engine.secrets`; `shared.cloud.get_secrets_store`; AWS/GCP `SecretsStore` adapters | Keep authorization-before-fetch, backend capability checks, provider deadlines, and the bounded in-process secret cache. Secret-store abstraction is already complete and is not part of this issue. |
| Configuration | `config/_guacamole_settings.py`, `config/settings.py`, `config/_env_manifest.py`, `config/env-manifest.json` | Reuse the existing names/defaults. Bind and normalize them once into client config; do not add a second env namespace or let the adapter reread settings. Keep public and internal URLs distinct. |
| API and WebSocket admission | `mission_control.api.guacamole`, its serializers/permissions, `config.middleware.CTFAccountBoundaryMiddleware`, `config.websocket_auth.CTFAccountWebSocketBoundary`, `config.asgi` | Keep request shape, session/API-token scope, active actor, temporary-participant admission, origin validation, and WebSocket identity gates unchanged. No new route is required. |
| Capacity and threading | `mission_control.terminal_sessions`, `terminal_executor`, `guacamole_bootstrap`, `config/_terminal_settings.py` | Preserve per-worker/per-user caps, bounded executor queues, DB connection cleanup, retryable saturation behavior, idle/max-duration enforcement, and blocking Guacamole/secret work off the event loop/request thread. |
| Errors and observability | `BootstrapFailure`, `BootstrapQueueFull`, `WebSocketCloseCode`, `shared.errors.classify_user_message`, `shared.log_sanitize`, `shared.audit` | Translate once at the existing application/presentation boundaries. Reuse current safe envelopes, sanitized correlation logging, and connect/disconnect/access-denied audits; do not add a parallel client/service exception hierarchy. |
| Tests | ADR-019; `tests/mission_control`, `tests/engine/services`, `tests/engine/ssh`, and `tests/shared/cloud` patterns | Real entry-point tests use fake ports/factories while retaining real first-party authorization/orchestration. Concrete Guacamole-adapter tests alone exercise the urllib/crypto/retry wire boundary; concrete SSH-adapter tests alone exercise asyncssh. Do not patch CMS/Engine/Guacamole service functions. |

## Cross-Cutting Security And Validation Path

The intended design must continue through every layer below:

1. **HTTP and actor validation.** DRF Guacamole launch routes retain
   `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, the
   `MISSION_CONTROL_GUACAMOLE_READ` scope, `GuacamoleInstanceSerializer`, and
   `_validated`. Session-authenticated calls retain DRF `SessionAuthentication`
   and its CSRF enforcement. The actor always comes from server authentication;
   a port never accepts a caller-supplied owner id.
2. **Temporary-account and WebSocket admission.** The narrow participant HTTP
   prefix remains governed by `CTFAccountBoundaryMiddleware`. Browser terminal
   sockets remain behind `AllowedHostsOriginValidator`, `AuthMiddlewareStack`,
   `CTFAccountWebSocketBoundary`, `SSHConsumer`'s anonymous/UUID checks, and
   terminal session/executor admission. Port injection must not create a route
   around these gates.
3. **Workspace and realized-resource authorization.** CMS first authorizes the
   request's persisted workspace binding. Engine then resolves only an active
   user-owned range or owned NGFW, requires READY, validates the UUID/role and
   declared `ssh`/`rdp` participant channel, normalizes the realized host/user
   fields, and requires a credential reference. A fake connection factory is
   invoked only after this path succeeds.
4. **Provider and secret handling.** `CLOUD_PROVIDER` remains composition-root
   validated against the installation registry; `get_secrets_store()` requires
   the backend's `SECRETS` capability. SSH keys/RDP passwords are fetched only
   after authorization, held in the existing bounded in-memory cache, and
   passed directly to the adapter/client in memory. They never enter port
   configuration, persistence, logs, audit payloads, URLs, or error bodies.
5. **Guacamole configuration and egress validation.** The setting binder keeps
   `GUACAMOLE_BASE_URL` as the browser-facing URL/path and
   `GUACAMOLE_API_BASE_URL` as the server-to-server endpoint. Only the internal
   token endpoint is required to pass the existing HTTP(S)-scheme check; a
   relative public `/guacamole` path remains valid. Retry attempts are bounded
   to at least one, delay to at least zero, and the HTTP request retains its
   finite timeout. URLs are deployment-controlled and never accepted from a
   request.
6. **Cryptographic and response shape validation.** Preserve the exact
   JSON-auth payload, HMAC-SHA256, AES-CBC/zero-IV/PKCS padding, accepted hex-key
   lengths, form-encoded `data` POST, transient status set, and fatal malformed
   response behavior. The concrete client may not leak `urllib` exceptions or
   response bodies through its public contract. The issue does not authorize a
   protocol, algorithm, signing, expiry, or retry-semantic change.
7. **SSH transport validation.** Preserve optional provisioner-recorded host-key
   pinning; never make `known_hosts=None` the convenience path for a new
   adapter. Private keys are parsed in memory, the tmux identifier is sanitized
   before reaching the remote command, and each failed/closed connection still
   releases process, socket, task, and session-cap resources.
8. **OS/process and network exposure.** This refactor adds no subprocess,
   command-line, container-argument, temp-file, or shell transport. On AWS the
   portal receives only the Guacamole secret reference in Docker configuration
   and `entrypoint.sh` exports the fetched value; on GCP the renderer/ConfigMap
   carries `GUACAMOLE_SECRET_ID` and the non-secret public/internal URLs while
   Secret-backed env and the entrypoint hydrate values. Secret material must not
   appear in argv, Helm values/history, generated runtime files, process
   diagnostics, or logs. Keep
   existing portal-to-Guacamole and portal/guacd-to-range network and security
   group/NetworkPolicy paths; a client abstraction is not permission to widen
   egress or dial a request-provided host.
9. **Error envelopes, logging, and persistence.** Expected Guacamole failures
   still become a bounded `BootstrapFailure`; queue pressure remains a 503 with
   `Retry-After`; terminal failures retain existing close-code categories.
   Provider messages, private hosts, secret references/values, encrypted
   payloads, auth tokens, and signed URLs never cross the user envelope or log
   boundary. Bootstrap errors remain single-line/500-character bounded. The
   only token-bearing persistence remains `result_url`, with current TTL,
   row-lock single consumption, immediate clearing, and pruning.

## Extensibility Seam

The required future-proof parameter is the configured adapter/factory, not a
provider selector:

- Guacamole session orchestration accepts a `GuacamoleClient` dependency; the
  production default comes from `get_guacamole_client(GuacamoleClientConfig)`.
  The config keeps public URL, internal API URL, retry policy, and finite request
  timeout independently variable, so a later HTTP implementation or timeout
  policy does not edit authorization, payload DTOs, bootstrap persistence, or
  browser delivery.
- Terminal construction accepts a `TerminalConnection` factory after connection
  facts are authorized/resolved. A later SSH implementation can replace
  asyncssh without changing CMS workspace policy, Engine lookup/secret logic,
  the WebSocket bridge, audit events, or terminal capacity controls.

Both defaults are explicit composition choices. Avoid process-wide mutable
singletons: they retain signing secrets, make settings overrides order-dependent,
and turn tests back into global-state manipulation.

## Whole-Repository Surfaces In Scope

- Architecture/enforcement: ADR-001, ADR-005, ADR-019, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`, and `scripts/adr_guard`.
- Application/runtime: `shared.remote_access`; `engine.ssh`, `engine.services`;
  `cms.services._range_access`; Mission Control Guacamole service/builders,
  bootstrap model/lifecycle, API/legacy adapters, terminal consumer/executor,
  session registry, error mapping, logging, and audit.
- Configuration: `config/_guacamole_settings.py`, the retry settings currently
  in `config/settings.py`, `_terminal_settings.py`, `_env_manifest.py`, and the
  committed env manifest. No new deployment knob is required.
- Host/deployment invariants: portal `entrypoint.sh`; AWS portal SSM/user-data
  and Guacamole security groups; GCP runtime renderer, Helm/Kustomize env/Secret
  bindings, access-node placement, and NetworkPolicies; public/internal
  Guacamole routing; portal worker/process limits.
- Verification: Mission Control public-flow/bootstrap/consumer suites, Engine
  service and SSH adapter suites, config/env-manifest tests, layer/import checks,
  Ruff, and ADR guard. Deployment validators are required only if implementation
  actually edits their surfaces.

## Gotchas And Anti-Patterns

- Do not put Guacamole under `shared.cloud`, branch on `CLOUD_PROVIDER`, add a
  backend capability, or create identical AWS/GCP Guacamole adapters.
- Do not conflate Guacamole SSH (a browser gateway payload) with the live
  `TerminalConnection` used by the WebSocket bridge, or reuse either as a
  secret-store abstraction.
- Do not introduce a generic remote-access request, a duplicate connection-info
  DTO, another `TerminalConnection` protocol, duplicate validation, a second
  retry loop, a new exception family, or a second bootstrap workflow.
- Do not inject an already-created connection, a user/target-authorized service
  result, or a fake CMS/Engine service. Inject only the external client or final
  connection constructor, after real policy gates.
- Do not use Django settings/import strings, environment-selected fake classes,
  monkeypatched first-party factories, or mutable registries as test DI. Keep
  the dependency explicit and keyword-only.
- Do not let the client or SSH adapter query ORM state, resolve secrets, perform
  ownership checks, emit HTTP/WebSocket responses, enqueue work, or persist
  tokens. Those are existing owners' responsibilities.
- Do not merge public/internal Guacamole URLs, move blocking work onto the event
  loop/request thread, remove retry/time/capacity bounds, or memoize a client
  carrying secret configuration globally.
- Do not weaken host-key verification, log credential-bearing request objects or
  final URLs, surface raw external exceptions, or change status/close-code/API
  envelopes as incidental cleanup.
- Do not replace all concrete-adapter tests with fakes. Fakes prove orchestration
  substitutability; focused adapter tests must still prove JSON-auth crypto/wire
  compatibility, retry classification, asyncssh mapping, host-key handling, and
  cleanup at the actual library boundaries.

## Non-Goals And Implementation Boundaries

- No implementation is performed by this preflight.
- No secret-store, secret-cache, provider-selection, persistence, database
  schema/migration, route, serializer, API response, WebSocket protocol, audit
  vocabulary, or deployment-topology change.
- No change to Guacamole JSON-auth wire format, signing/encryption, token expiry,
  browser URL delivery, retry classifications, affinity, or Guacamole database.
- No change to SSH credential derivation, target/participant/workspace
  authorization, tmux semantics, host-key policy, terminal byte protocol,
  capacity limits, idle/max-duration policy, or reconnect behavior.
- No generic service locator, DI container, plugin system, remote-access
  framework, new cloud abstraction, or CMS forwarding layer beyond carrying the
  narrow terminal constructor dependency through its existing authorization
  facade.
