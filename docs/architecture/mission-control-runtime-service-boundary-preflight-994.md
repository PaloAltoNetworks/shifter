# Mission Control Runtime Service Boundary Preflight (#994)

Status: architecture decision / pre-implementation guidance

Date: 2026-07-19

Issue: GitHub #994, "arch: clarify whether mission_control should call
engine.services directly or front through cms."

This is a requirement-free architecture decision. The GitHub issue is the
shipping contract. This note records boundaries and guardrails; it is not an
implementation plan.

## Decision

`mission_control` calls the public service facade of the domain that owns the
operation:

- `cms.services` owns catalog/content operations, desired-state range lifecycle,
  and control-plane orchestration. CMS may delegate realization work to
  `engine.services` as part of those workflows.
- `engine.services` owns realized infrastructure/runtime state and data-plane
  access. `mission_control` therefore calls it directly for browser-terminal
  connection creation, SSH/RDP connection resolution, and NGFW terminal access.
- `mission_control` owns presentation transport and delivery: HTTP/DRF request
  validation, WebSocket admission and close codes, terminal capacity, Guacamole
  URL/token construction, and the bounded bootstrap lifecycle.

The resulting dependency graph is intentional, not an accidental diamond:

```text
mission_control ----> cms.services ----> engine.services
       |
       +-------------------------------> engine.services
          realized runtime access only
```

Presentation is not required to have exactly one downstream service layer. It
must depend only on public owning-domain facades. Adding CMS forwarding methods
for Engine-owned access would add a patch seam and exception/DTO coupling without
adding policy, validation, transactionality, or ownership. A dedicated runtime
facade is likewise unjustified while `engine.services` already is the stable
runtime facade.

This decision extends ADR-001 (recorded as rule ADR-001-R4). The explicit
`engine.services` and `cms.services` allowances in
`scripts/check_layer_imports/layer_imports.yaml` remain the enforced boundary,
and the `mission_control -> engine.services` seam is narrowed further to a
per-symbol allowlist (`allowed_symbols` in the same file): presentation may
import from `engine.services` only the sanctioned realized-runtime symbols
(`SSHConnection`, `connect_terminal`, `connect_ngfw_terminal`,
`get_ssh_connection_info`, `get_rdp_connection_info`, `get_ranges_for_ngfw`).
Importing any other `engine.services` symbol, or a bare `import engine.services`
module import that hides which symbol is used, is a layer-import violation, so
control-plane engine operations keep fronting through `cms.services`. Both the
standalone `check_layer_imports.py` and the `adr_guard.py` layer-imports gate
enforce this. This decision does not permit imports of `engine.models`,
`engine.ssh`, `engine.secrets`, `engine.services._*`, `engine` package-root
shortcuts, CMS models, or private CMS service modules.

## Existing Ownership And Contracts To Preserve

| Concern | Canonical incumbent | Boundary requirement |
| --- | --- | --- |
| Runtime resource authority | `engine.models.Range`, `engine.models.Instance`; public access through `engine.services._terminal` re-exports in `engine.services` | Engine resolves the user-owned active range/NGFW, requires READY state, checks the requested instance/role and declared participant channel, and only then resolves credentials. No ORM object or raw realization state crosses to presentation. |
| Realized-state projection | `engine.services._common` and `_terminal` | Keep provider/legacy key normalization and bounded connection projections in Engine. `provisioned_instances` is realized state, not a CMS RangeSpec and not a reason to create a duplicate schema. |
| Access-channel policy | `cms.scenarios.schema.ParticipantAccessConfig.channel`, realized `participant_access_channels`, and `engine.services._terminal._require_declared_participant_channel` | The closed `ssh`/`rdp` realization binding is authorization input. `shared.aces.presentation.ACCESS_CHANNEL_*` and `RangeAccessChannel` are read-only UI availability projections, not equivalent vocabulary and never authorization evidence. |
| Provider selection | `config._runtime_env.resolve_cloud_provider`, `config._cloud`, the installation backend registry, and `shared.cloud.get_secrets_store` | Consume the composition-root-validated `CLOUD_PROVIDER`; require the registered secrets capability. Do not add view-local defaults or provider branches. |
| Secret retrieval | `engine.secrets`, `shared.cloud.types.SecretsStore`, AWS/GCP secret-store adapters | Fetch only after authorization/readiness. Preserve bounded provider deadlines and the TTL/max-entry in-process cache. Secret values stay in memory and never enter CMS state, audit payloads, logs, or API errors. |
| SSH transport | `engine.ssh.SSHConnection`, constructed only by public Engine services | Mission Control may hold the returned connection contract but must not import the transport implementation directly or recreate key parsing/tmux behavior. |
| Guacamole delivery | `mission_control.guacamole`, `mission_control.guacamole_bootstrap`, `GuacamoleBootstrapRequest`, and Guacamole API/view serializers | Keep signing/encryption, allowed URL schemes, bounded worker/TTL settings, owner-scoped polling, atomic single-use URL delivery, and pruning in presentation. Do not move Guacamole construction into CMS or Engine. |
| WebSocket capacity | `mission_control.terminal_sessions`, `mission_control.terminal_executor`, `config._terminal_settings` | Preserve per-process/per-user caps, bounded executor admission, DB connection cleanup, idle/max-duration timeouts, and retryable saturation close behavior. Blocking DB/secret work does not run on the event loop or the shared page-render executor. |
| Error delivery | Engine's existing `ValueError`/`PermissionError` behavior; `shared.errors.classify_user_message`; `shared.api.errors`; `BootstrapFailure`; `WebSocketCloseCode` | Translate at the presentation boundary into authored, bounded messages/statuses/close codes. Never serialize raw provider exceptions, secret references, stack traces, or a second CMS exception hierarchy. |
| Logging and audit | module loggers, `shared.log_sanitize`, `shared.audit.audit_session_event`, trusted client-IP policy | Keep stable non-secret correlation fields, sanitize user/resource-controlled values, and preserve connect/disconnect/access-denied audit behavior. Credentials, Guacamole tokens, signed payloads, raw realization state, and secret-store responses are never logged. |
| Tests | ADR-019; real service/ORM behavior suites under `tests/mission_control` and `tests/engine/services`; cloud/network fixtures | Drive presentation through real Engine services and rows. Mock SDK/Guacamole/SSH transport boundaries, not `engine.services` or new CMS forwarding methods. |

## Cross-Cutting Security And Validation Path

The intended design passes through all of these gates:

1. **HTTP/DRF authentication and request shape.** Legacy views retain
   `login_required`; `/api/v1` retains `IsAuthenticatedSessionOrApiToken`,
   `HasMissionControlActor`, the `MISSION_CONTROL_GUACAMOLE_READ` scope, and
   `GuacamoleInstanceSerializer`/`_validated`. The authenticated actor, not a
   caller-supplied user id, is passed to Engine.
2. **WebSocket origin/account/session admission.** The terminal route remains
   behind `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and
   `CTFAccountWebSocketBoundary`; `SSHConsumer` rejects anonymous/malformed
   scopes and reserves bounded session/executor capacity before expensive work.
3. **Engine object authorization and shape projection.** Engine validates the
   user and opaque target identifier, selects only a current user-owned active
   resource, requires READY, enforces NGFW role/request ownership or the declared
   participant access channel, and defensively normalizes provider realization
   state. Presentation does not duplicate these checks.
4. **Provider/config capability gate.** `CLOUD_PROVIDER` is resolved once at the
   composition root against the installation registry. `get_secrets_store()`
   requires the selected backend's `SECRETS` capability before choosing the AWS
   or GCP adapter. Existing `config._env_manifest`/`config/env-manifest.json`
   bindings remain authoritative; this decision adds no setting.
5. **Secret-handling gate.** Dynamic SSH/RDP values flow from provider secret
   storage through `engine.secrets` into process memory after authorization.
   `GUACAMOLE_JSON_AUTH_SECRET` and the exceptional deployment-scoped
   `DC_DOMAIN_PASSWORD` continue to be hydrated fail-closed by the portal
   entrypoint from secret references. Secret values are not placed in process
   argv: entrypoint subprocess arguments carry references, and parsed secret
   material flows through stdin/environment; runtime connection fetches use SDK
   request bodies/in-memory objects. A missing Guacamole signing secret fails the
   view with 503; malformed hex is rejected by the existing signing builder and
   remains inside the bounded bootstrap error envelope.
6. **Transport and egress gate.** AsyncSSH receives the private key in memory;
   Guacamole receives a signed/encrypted JSON-auth payload over its configured
   HTTP(S) API after explicit scheme validation. Browser delivery contains only
   the short-lived Guacamole token URL, owner-scoped and consumed once. No shell,
   task command, container/job specification, or provisioner argv is introduced.
7. **Error-envelope and observability gate.** Engine validation failures map to
   existing close codes or fixed user-message categories. Unexpected/provider
   details remain in sanitized operational logs; bootstrap failure strings and
   statuses are bounded before persistence. Session audit uses the shared event
   contract and trusted-proxy client-IP policy.
8. **Persistence gate.** CMS continues to own desired-state `RangeInstance`
   records; Engine owns realized Range/Instance state. Mission Control persists
   only the bounded Guacamole bootstrap record. A token URL is TTL-bounded,
   atomically consumed with `select_for_update()`, cleared after delivery/expiry,
   and pruned in bounded batches. No connection credential is copied into CMS.

## Extensibility Seam

The seam for the next runtime-access variation is the public `engine.services`
facade: accept the authenticated actor plus a bounded opaque target identifier,
authorize against current Engine-owned realization state, normalize any new
provider metadata behind Engine's existing projection helpers, and return only
the values the presentation transport needs. Mission Control then applies its
existing delivery/capacity/error envelope.

A new provider belongs behind the existing backend registry and `SecretsStore`
port. The protocol parameter for another declared guest-access variation belongs
in the existing closed `ParticipantAccessConfig.channel` vocabulary, its realized
`participant_access_channels` binding, Engine's policy/service, and the Mission
Control delivery adapter. The UI-only `ACCESS_CHANNEL_*` map may advertise that
capability but cannot authorize it. Move a contract into `shared` only when more
than one domain genuinely consumes a stable neutral contract; do not pre-create
a generic remote-access framework or make CMS a catch-all facade. CMS joins the
flow only when a user operation actually changes catalog or desired lifecycle
state.

## Whole-Repository Surfaces In Scope

- Architecture policy: ADR-001, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`, its checker/tests, and
  `scripts/adr_guard`.
- Presentation: Mission Control legacy views, DRF Guacamole endpoints and
  serializers/permissions, WebSocket routing/consumer, terminal executor/session
  registry, Guacamole builders/bootstrap persistence, audit and error mapping.
- Domain services: public `cms.services` and `engine.services`; Engine realized
  state projection, secret retrieval, and SSH transport.
- Composition/config: ASGI origin/auth middleware, cloud-provider resolution,
  env manifest, Guacamole/terminal/cache settings, portal entrypoint hydration,
  and installation backend capabilities.
- Runtime/deployment: AWS/GCP secret-store adapters, Guacamole internal/public
  URL split, portal worker/process limits, database cleanup, and token pruning.
- Verification: behavior suites under `tests/mission_control`,
  `tests/engine/services`, config/entrypoint tests, layer-import checker tests,
  import-linter, and the ADR guard.

## Gotchas And Anti-Patterns

- Do not front Engine-owned runtime functions through CMS solely for a one-arrow
  presentation diagram. A forwarding layer is not orchestration.
- Do not introduce a second connection DTO/schema, validator, exception family,
  secret cache, ownership check, provider switch, audit event, or logging helper.
- Do not conflate declared `ssh`/`rdp` authorization bindings with the
  `browser_terminal`/`guacamole_*` presentation projection or infer permission
  merely because a UI capability is advertised.
- Do not treat `provisioned_instances` as a CMS/DSL RangeSpec, expose raw state,
  or resolve a target by display role/name when the UUID binding exists.
- Do not import private service modules, models, `engine.ssh`, `engine.secrets`,
  or package-root re-exports across the layer boundary. Lazy imports and
  `TYPE_CHECKING` do not make a semantically private dependency acceptable.
- Do not fetch a credential before owner/readiness/channel checks; log or persist
  a password/private key/token/signed payload; include one in argv; or surface a
  provider/secret-store exception to the browser.
- Do not move blocking DB, cloud, or Guacamole work onto the event loop/request
  thread, remove admission bounds, or replace PostgreSQL row locking with a
  process-local check-then-write sequence.
- Do not change HTTP status/error-body/WebSocket close semantics or audit
  cardinality as a side effect of boundary cleanup.
- Do not grow first-party mock topology. Tests should prove the real path while
  replacing only cloud SDK, Guacamole HTTP, and SSH network transports.

## Non-Goals And Implementation Boundaries

- No runtime imports, service methods, call signatures, return shapes, exception
  behavior, database schema, migrations, API schema, or deployment settings are
  changed by this preflight.
- No CMS forwarding methods, dedicated runtime facade/package, shared generic
  remote-access model, repository layer, service locator, or plugin framework.
- No redesign of range lifecycle, CMS/Engine persistence, Guacamole token
  protocol, terminal UX, CTF access, ACES participant projections, or provider
  realization.
- Issue #991's remote-access decomposition remains separate and must preserve
  this ownership decision rather than use decomposition to reverse it.
