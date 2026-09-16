# Mission Control Remote-Access Session Preflight (#991)

Status: architecture decision / pre-implementation guidance

Date: 2026-07-21

Issue: GitHub #991, "refactor: mission_control views orchestrate multiple
external systems directly"

This is a requirement-free run. The GitHub issue is the shipping contract. This
note fixes the intended boundary and its repository-wide guardrails; it is not an
implementation plan.

## Decision

Put Guacamole session orchestration behind one transport-neutral application
service owned by `mission_control`. Its launch entry point accepts the
authenticated actor, a closed access kind, and the opaque target identifier. It
binds the existing Guacamole runtime configuration, enqueues the existing
bounded bootstrap work, and, inside that worker, performs exactly this sequence:

1. call the sanctioned public `engine.services` runtime resolver;
2. adapt its authorized connection projection into the existing
   `GuacRDPUrlRequest` or `GuacSSHUrlRequest`;
3. call the existing `mission_control.guacamole` broker; and
4. let the existing bootstrap lifecycle persist and deliver the resulting URL.

The HTTP/DRF adapter authenticates, validates request shape, obtains the actor,
calls that one application-service entry point, and renders the existing queued
response or existing error contract. It does not select Engine functions, read
Guacamole settings/secrets, construct credential-bearing Guacamole requests,
build worker lambdas, or translate Engine failures.

This is an internal decomposition of the presentation layer, not a reversal of
the ownership decision in
`docs/architecture/mission-control-runtime-service-boundary-preflight-994.md`:

- Engine owns realized runtime state, owner/readiness/access-channel policy, and
  credential resolution.
- Mission Control owns the browser-session use case, Guacamole JSON-auth
  adaptation, async bootstrap, and HTTP delivery.
- CMS does not join this path. A CMS forwarding method would add no policy or
  transaction and is prohibited by ADR-001-R4.

No new ADR is needed. ADR-001-R4 already authorizes only the required
`mission_control -> engine.services` symbols, ADR-019 controls test seams, and
the #929/#939 Guacamole notes own the asynchronous and token-lifecycle
constraints.

## Boundary Contract

The service boundary is one public use-case call, not a framework, registry, or
generic remote-access domain. Keep the inputs narrow:

- authenticated Django actor from the existing request identity machinery;
- a closed access kind that preserves the distinct policies for range RDP,
  range SSH, and NGFW SSH; and
- one bounded opaque target identifier.

Return the existing bootstrap state needed to render the 202 response, or an
existing safe expected-failure contract. Do not return Engine ORM objects,
credential dictionaries, signing configuration, Guacamole payloads, or the
final bearer URL to the launch view. The final URL remains available only from
the owner-scoped, single-consume bootstrap status endpoint.

The service must be HTTP-neutral. `JsonResponse`, DRF `Response`, serializers,
URL reversal, request objects, and HTTP error envelopes stay in the adapter.
The current `_ViewError(JsonResponse)` and response-body re-parsing are therefore
not valid service contracts. Expected worker failures already have
`BootstrapFailure`; safe synchronous readiness/config failures should reuse the
existing safe user-error/error-mapping machinery rather than introduce another
exception hierarchy.

Do not add a second connection schema. Consume the existing Engine public
projections at one mapping site and use the existing Guacamole request
dataclasses as the adapter inputs. `engine.services.SSHConnection` is already a
sanctioned public re-export; a second Mission Control `_SSHConn` protocol is not
a new contract. The untyped Engine SSH/RDP dictionaries are existing technical
debt, not permission for a duplicate service DTO in this issue.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #991 |
| --- | --- | --- |
| HTTP request shape and OpenAPI | `mission_control.api.guacamole`, `GuacamoleInstanceSerializer`, `_validated`, queued/status serializers | Preserve canonical `/api/v1/mission-control/` routes and response shapes. Do not add manual JSON parsing or a second serializer for the same body. |
| Authentication and actor | `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `mission_control_actor_user`, `MISSION_CONTROL_GUACAMOLE_READ` | The service receives the server-derived actor only; never accept a user id/owner from request data. |
| Temporary-participant admission | `config.middleware.CTFAccountBoundaryMiddleware` and its narrow `/api/v1/mission-control/guacamole/` prefix | New routes under this prefix become participant-reachable and require an explicit security review. This refactor should add none. |
| Runtime authorization/data | `engine.services.get_rdp_connection_info`, `get_ssh_connection_info`, `connect_ngfw_terminal`; their `_terminal`/`_common` implementation | Reuse active-owner, READY, UUID/role, host, declared-channel, and credential-reference checks. Do not query Engine models or repeat authorization in Mission Control. |
| Provider secret access | `engine.secrets`; `shared.cloud.get_secrets_store`; AWS/GCP secrets adapters, deadlines, retry/cache policy | Resolve values only after Engine authorization, in the bootstrap worker. No new SDK client, provider branch, cache, or secret DTO. |
| Guacamole broker | `mission_control.guacamole`, `GuacRDPUrlRequest`, `GuacSSHUrlRequest`, token exchange retry/scheme validation | Keep payload signing/encryption and `/api/tokens` HTTP in this adapter. Do not create a second Guacamole client or move it into Engine/CMS. |
| Session identity and protocol mapping | existing `guacamole_identity`, SFTP-root mapping, and connection-name construction | Centralize these policies behind the application service; do not duplicate them per view or conflate them with account authorization. |
| Bootstrap workflow | `mission_control.guacamole_bootstrap`, `GuacamoleBootstrapRequest`, and bootstrap response/status/open helpers | Preserve bounded slots/workers, 202 + polling, TTL, DB connection cleanup, sanitized failure persistence, atomic one-time URL delivery, expiry, and bounded pruning. |
| Errors | `shared.errors.classify_user_message`/`safe_user_message`, `shared.api.errors`, `BootstrapFailure`, `_clean_error_message` | Map once at the service/presentation edge. Never persist or return raw Engine, provider, urllib, crypto, or secret-store exception text. |
| Logging | module loggers; `shared.log_sanitize.safe_log_value`, `safe_log_fingerprint`; request/bootstrap IDs | Log non-secret kind, safe target/user identifiers, result class, duration, and saturation only. Never log credentials, payloads, signing keys, tokens, or URLs. |
| Persistence | `GuacamoleBootstrapRequest` and `consume_ready_url()` | No repository abstraction, second table, Redis copy, audit copy, or durable connection DTO. The existing row is the lifecycle authority. |
| Tests | ADR-019; Mission Control URL behavior suites; Engine service behavior suites; urllib and cloud SDK fakes | Keep the real view -> application service -> Engine/Guacamole path in repository tests; replace only genuine external transport boundaries. |
| Architecture enforcement | ADR-001-R4, ADR-019, `.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR guard | Import only public allowlisted Engine service symbols. Do not weaken or baseline away a violation. |

## Cross-Cutting Security And Validation Path

The intended design must pass every layer below.

1. **Request admission, auth, and CSRF.** The request first passes
   `CTFAccountBoundaryMiddleware`. DRF then retains token/session
   authentication (with session CSRF enforcement), `HasMissionControlActor`,
   the exact Guacamole-read scope, method routing, UUID path conversion where
   present, and `GuacamoleInstanceSerializer` validation. The application
   service receives the derived active actor and validated identifier, never
   raw ownership claims.
2. **Engine authorization and realized-state shape.** The selected public
   Engine resolver requires a user and target, locates only that user's active
   range or owned NGFW, requires READY, checks instance/role/host and the closed
   realized `participant_access_channels` binding, then resolves credentials.
   The service must not prefetch credentials or replace these checks with UI
   availability, a display name/role, or presence of a secret reference.
3. **Provider capability and secret handling.** `CLOUD_PROVIDER` remains
   composition-root validated; `shared.cloud` selects the registered secrets
   capability. AWS/GCP request deadlines, retry limits, and the bounded
   reference-keyed secret cache remain authoritative. Private keys and RDP
   passwords exist only in worker memory long enough to build the encrypted
   Guacamole payload.
4. **Guacamole config shape.** Reuse `config._guacamole_settings`, the generated
   `config/env-manifest.json`, and the existing public/internal split:
   `GUACAMOLE_BASE_URL` is browser-facing while `GUACAMOLE_API_BASE_URL` is the
   server-to-server mint endpoint. Keep HTTP(S)-scheme validation, token retry
   knobs, worker/TTL/prune settings, and immediate fail-closed 503 behavior when
   the signing secret is absent. Do not add a setting for an internal class or
   function selection.
5. **Secret injection and OS/process exposure.** Portal startup receives only a
   Guacamole secret reference from AWS/GCP deployment binding; `entrypoint.sh`
   fetches and exports `GUACAMOLE_JSON_AUTH_SECRET` in process environment. The
   value, RDP/SSH credentials, signed/encrypted payload, and final token URL must
   not enter process argv, shell/SSM commands, temp files, ConfigMaps/Helm
   values, logs, metrics labels, traces, screenshots, or test artifacts. This
   refactor introduces no subprocess or deployment mutation.
6. **Network egress.** The broker validates the internal API URL scheme and uses
   its existing bounded urllib request/retry path. Preserve the internal/public
   URL distinction and existing Guacamole network policies/topology; never send
   the token-mint request to a caller-controlled URL.
7. **Error envelopes.** DRF authentication/permission/request-shape failures
   continue through `shared.api.errors`' canonical envelope. Existing
   Guacamole compatibility 503/status payloads remain as documented by
   `LegacyErrorSerializer`/`GuacamoleBootstrapStatusSerializer`; do not silently
   normalize response bytes during this refactor. Worker errors use authored,
   bounded messages/statuses through `BootstrapFailure` and bootstrap cleaning.
8. **Persistence and delivery.** The application service enqueues before any
   cloud/Guacamole blocking work. `GuacamoleBootstrapRequest` remains
   owner-scoped and TTL-bounded; the status endpoint atomically consumes and
   clears the bearer URL, and pruning removes expired rows. Credentials and
   payloads never become model fields.
9. **Observability.** Preserve request ID response correlation and bootstrap ID,
   protocol/target, queue-full, duration, status, expiry, consume, and prune
   signals. Internal hosts/provider-derived values require fingerprints when
   needed; secret values and bearer URLs are never observability dimensions.

## Extensibility Seam

The extension point is the closed access-kind dispatch inside the Mission
Control application service, parameterized by actor and target identifier. A
reasonable next browser-session variation (for example VNC or a new authorized
target kind) adds one Engine-owned resolver/policy branch if needed and one
Guacamole adapter mapping while reusing the same bootstrap, delivery, config,
error, and logging envelopes. It must not require editing every HTTP view's
credential orchestration.

Keep target kind separate from transport protocol: range SSH and NGFW SSH use
the same Guacamole protocol but have different ownership and connection-name
policies. Also keep the Guacamole JSON-auth expiry policy separate from the
bootstrap row TTL; both happen to be five minutes today but govern different
assets and must not be represented by one misleading setting.

Do not create a plugin registry, service locator, dependency-injection
container, generic `RemoteAccess` aggregate, or shared cross-domain DTO. Move a
contract to `shared` only after another domain genuinely consumes a stable,
non-secret neutral contract. In particular, `shared.remote_access` is the
participant-held OpenVPN capability governed by ADR-039; it is not the browser
Guacamole session use case and must not be reused based on its name.

The issue's rough "fake one port" acceptance describes the desired one-call
view seam, but ADR-019 is stricter about committed repository tests: it forbids
new first-party service patches/topology mocks. Do not invent an aggregate port
that hides Engine plus Guacamole merely to reduce a mock count. Unless ADR-019
is separately amended, URL behavior tests must call the real application
service and fake only the actual cloud SDK and Guacamole HTTP transports. A
focused pure orchestration test may inject explicit external adapter callables
without patching first-party functions, but those seams must correspond to real
I/O boundaries rather than bundle unrelated systems.

## Whole-Repository Surfaces In Scope

- Presentation/application: `mission_control.api.guacamole`, API serializers and
  permissions, current Guacamole view/build helpers, `mission_control.guacamole`,
  `mission_control.guacamole_bootstrap`, bootstrap model/status/open delivery,
  URL routing, and frontend consumers of the unchanged 202/poll contract.
- Runtime domain: the public `engine.services` facade and allowlisted terminal
  resolvers; Engine realized-state projection, ownership/access-channel policy,
  secret resolution, and the public `SSHConnection` re-export.
- Cross-cutting support: `shared.errors`, `shared.api.errors`,
  `shared.log_sanitize`, cloud-provider capability selection and secrets
  adapters/cache/timeouts.
- Composition/runtime: `config.middleware`, DRF authentication/exception
  settings, `_guacamole_settings`, env manifest, portal `entrypoint.sh`, AWS/GCP
  secret-reference binding, and Guacamole public/internal network topology.
  These are constraints to preserve; no deployment/config change is expected.
- Persistence/operations: `GuacamoleBootstrapRequest`, its transactionally
  single-use delivery, pruning command/service, worker limits, TTL, and DB
  connection cleanup.
- Verification/enforcement: Mission Control/Engine/Guacamole behavior suites,
  OpenAPI contract tests, env/config tests, boundary-mock policy, layer-import
  checker/import-linter, and ADR guard.

## Gotchas And Anti-Patterns

- Do not merely move `_resolve_and_build_*` from one `views/` file to another.
  A helper that imports HTTP responses, reads settings passed by a view, and
  raises `_ViewError` is still presentation-coupled orchestration.
- Do not resolve Engine credentials on the request thread. The application
  service must preserve the #929 worker boundary even though the launch view now
  makes one service call.
- Do not make CMS proxy Engine runtime services, import Engine models/private
  modules, or add symbols beyond ADR-001-R4's allowlist without an explicit
  architecture decision.
- Do not duplicate `Guac*UrlRequest`, request serializers, Engine connection
  projections, access-channel validation, identity fallback, SFTP mapping,
  error categories, logging sanitizers, bootstrap states, or token lifecycle.
- Do not conflate an Engine `SSHConnection` (live async terminal transport) with
  a Guacamole SSH connection description; the NGFW path may consume the former
  only as the existing authorized projection.
- Do not conflate UI capability projection (`browser_terminal`,
  `guacamole_*`) with the realized `ssh`/`rdp` authorization binding, or infer
  access because credentials happen to exist.
- Do not serialize raw exception strings, secret references, provider/account
  metadata, hosts, credentials, payloads, or token URLs into errors or logs.
- Do not change status codes, nested-versus-flat error shapes, polling headers,
  URL fields, single-use semantics, or OpenAPI as collateral cleanup.
- Do not add a second bootstrap worker/table/queue/repository or bypass row
  locking with a process-local check-then-clear sequence.
- Do not add a generic port solely to fake a first-party use case in tests or
  grow ADR-019's patch baseline. Tests should prove behavior across the new
  internal boundary.

## Non-Goals And Implementation Boundaries

- No issue implementation is performed by this preflight.
- No redesign of Engine authorization, provider selection, secret retrieval,
  credential caching/rotation, or range/NGFW persistence.
- No redesign of Guacamole JSON authentication, signing/encryption, retry,
  topology, token affinity, bootstrap UX, polling protocol, or token lifecycle.
- No new route, API version, request/response schema, persistence model,
  migration, setting, deployment value, audit event, or metrics framework.
- No unification with WebSocket/xterm terminal sessions, OpenVPN remote access,
  ACES participant-runtime contracts, or scenario-authored access schemas.
- No broad service-package, repository, plugin, or dependency-injection
  architecture. The boundary is the smallest Mission Control application use
  case that removes multi-system coordination from the view.
