# REV1 package boundaries and audit port preflight (#1523)

Status: architecture preflight; no runtime or enforcement change

Issue #1523 closes the gap identified by REV1 finding A4: the architecture
checks are green, but their hard-coded package sets omit installed first-party
apps. It also corrects audit dependency inversion. This record defines the
target boundary and the constraints the implementation must preserve; it is not
an implementation plan.

## Repository evidence

The installed first-party Django apps are `config`, `mission_control`,
`risk_register`, `engine`, `cms`, `management`, `shared`, and `ctf`.
`.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, both Python
implementations of the layer check, and `check_model_fks` currently enumerate
only six of the eight: `engine`, `cms`, `management`, `mission_control`,
`shared`, and `ctf`. Consequently, the existing gates pass without examining
`config` or `risk_register`.

The old in-app `documentation` package is not an installed or tracked Django
app. ADR-038 retired it in #1591 in favor of the top-level MkDocs site. It must
not be restored or classified as a live package merely because REV1 A4 named it
before that retirement.

Audit is currently feature-owned in the wrong direction:

- domain, presentation, and composition code imports
  `risk_register.models.AuditLog` and `risk_register.services` to emit events;
- risk-register views bypass the service and call `AuditLog.log()` directly;
- `shared.api_tokens.audit`, `shared.context_processors`, and
  `shared.api.bootstrap` import upward from `risk_register`;
- the audit vocabulary is nested on the ORM model, so emitters depend on both
  storage ownership and Django persistence types;
- `config.health_checks` also reaches into `risk_register.audit_health`.

## Package taxonomy and dependency direction

Every tracked local Django `AppConfig` and every local package referenced by
`INSTALLED_APPS` has exactly one classification:

| Classification | Packages | Boundary |
| --- | --- | --- |
| Domain | `engine`, `cms`, `management`, `ctf`, `risk_register` | Own business state and behavior. May use `shared` and only explicitly allowed public service facades of another domain. |
| Presentation | `mission_control` | Owns HTTP/WebSocket presentation orchestration. May use `shared` and explicitly allowed public domain service facades; never domain models. |
| Support/contracts | `shared` | Owns neutral contracts and cross-cutting platform primitives. It must not import domain, presentation, or composition packages. |
| Support/composition | `config` | Owns settings, startup binding, root URL/ASGI wiring, identity-provider adapters, and cross-domain read composition. It may wire explicitly named public services, URL/routing surfaces, and adapter factories; it must not import domain models or private implementation modules. |

`scripts/check_layer_imports/layer_imports.yaml` remains the canonical
package/dependency policy and should carry this classification rather than
adding another independent package list. The other enforcement surfaces may
need static representations, but parity with the canonical policy must be a
tested invariant. A new local `AppConfig`, or a new local package added to
`INSTALLED_APPS`, fails closed until classified. Third-party apps are identified
by the absence of a tracked local package/AppConfig, not maintained in an
ever-growing third-party allowlist. Dynamic `INSTALLED_APPS` expressions that
the checker cannot resolve also fail closed.

The composition role is narrow, not a general exception to ADR-001. Root URL
and ASGI modules may include app `urls`/`routing`; startup may bind a concrete
adapter to a neutral port; cross-domain controllers may call public query
services. `config` may not query `risk_register.models` directly, and
`config.api_dashboard` may not consume the CTF-owned `ctf.bridges` outbound
bridge as an inbound API. Those reads belong behind the owning domains' public
service facades and must return bounded primitives/contracts rather than ORM
objects.

Historical migration dependencies and frozen `apps.get_model()` lookups are
not runtime layer imports. Current model relationships remain subject to the
zero-cross-layer-FK rule. Do not rewrite old migrations to make static policy
output look cleaner.

## Neutral audit boundary

The audit dependency direction is:

```text
domain / presentation / config emitters
                  |
                  v
 shared audit contracts + emission policy + health
                  |
            AuditWriter port
                  |
                  v
 risk_register compatibility persistence adapter
                  |
                  v
 existing AuditLog model, table, migrations, admin and read API
```

The neutral `shared` boundary owns the canonical action, entity, and actor
vocabulary; `AuditEvent`, request/auth/session/state context value objects; the
writer protocol; trusted request attribution helpers; strict versus
best-effort emission policy; sanitized operational logging; and process-local
degradation state. There must be one vocabulary and one event shape. The ORM
model derives its field choices from that vocabulary rather than defining a
second enum schema.

The concrete adapter owns only ORM mapping and persistence. It may import
`risk_register.models`; emitters may not. Direct `AuditLog.log()` is confined to
the adapter. Risk-register admin, serializers, query views, migrations, and
behavior tests may still read the model because they own or verify the durable
store. No audit API may return an ORM object across the port; callers do not use
the current return value in runtime code and should observe durable behavior by
querying the owning read surface in tests.

Binding belongs at the existing Django composition/startup seam
(`config.apps.PortalConfig.ready` or an equivalently explicit startup binding),
not in a lazy import from `shared` and not in import-time model side effects.
The binding is the extensibility seam: one `AuditWriter` implementation is
selected without changing emitters. Missing or conflicting binding is a startup
configuration error, not a silent no-op. This issue does not add another
backend, queue, environment selector, or plugin framework.

The shared emission policy preserves the two existing failure modes:

- best-effort events mark audit health degraded, emit sanitized internal
  diagnostics, and do not break the caller;
- security-control events remain strict and are written inside the caller's
  existing `transaction.atomic()` boundary so a persistence failure rolls back
  the role, identity, or account mutation it describes.

The concrete writer must raise persistence faults to that policy layer; it must
not add a second catch/swallow hierarchy. Existing HTTP and domain lifecycle
events sometimes produce distinct rows for request attribution and state
transition. Port extraction must preserve tested event cardinality and meaning,
not accidentally double-emit or deduplicate them. Redesigning that audit model
requires a separate contract decision.

## Cross-cutting controls that remain authoritative

| Concern | Canonical incumbent and required behavior |
| --- | --- |
| Authentication and authorization | `config.oidc`, `config.identity_platform`, `config.user_type_sync`, `config.organizer_authority`, `shared.api_tokens.authentication`, DRF permission classes, and CTF/terminal admission remain authoritative. Audit records outcomes; it never grants access or replaces a policy check. |
| Request attribution | `config.middleware.RequestIDMiddleware` and the existing `select_trusted_client_ip`/`get_client_ip` behavior are one contract for HTTP and ASGI consumers. Trust the configured rightmost proxy hop and fall back to `REMOTE_ADDR`; never trust the client-controlled leftmost XFF entry. |
| Configuration shape | `config.settings._env_int`, `AUDIT_TRUSTED_PROXY_HOPS`, `config._env_manifest`, `config/env-manifest.json`, and their tests remain the binding path. The existing audit setting is currently absent from the generated manifest because helper-based reads need an explicit binding; reconcile that gap rather than creating a second setting parser. No new audit backend environment variable is justified. |
| Secret and PII handling | Raw bearer tokens, passwords, cookies, authorization headers, credential values, private keys, provider payloads, and full request headers never enter `AuditEvent`, logs, argv, or environment. Event state is a bounded JSON-safe summary. Existing deliberately retained attribution fields (actor id, email where already required, source IP, user agent, request id) do not appear in operational logs without the established `shared.log_sanitize`/fingerprint treatment. |
| Logging and health | Reuse ECS logging from `config.logging`/`config._logging_config`, `shared.log_sanitize`, and the existing coarse `django-health-check` response. Health exposes only degraded/not-degraded; exception class/count/time stay internal and event payloads or database details never enter the health envelope. |
| Error envelopes | DRF errors continue through `shared.api.errors.api_exception_handler`/`api_error_response` and `shared.errors`. Audit persistence exceptions are never serialized to clients. Strict exceptions may abort a transaction but must still reach the existing sanitized HTTP error handling, not a new audit-specific API envelope. |
| Persistence | Keep `risk_register.AuditLog`, its table, indexes, migrations, archive command, admin, and read serializer stable. The port extraction is dependency inversion, not a table/app-label migration. Preserve JSONField serialization checks, IP validation, field bounds, immutability expectations, and transactional behavior. |
| Testing | Reuse behavior tests that drive real services and assert real ORM rows. ADR-019 forbids growing first-party patch topology; port work should remove obsolete `cms.services`/`mission_control.views` audit re-export patch seams and ratchet the mock baseline when possible, not rename them into a new baseline allowance. |

The contract passes no audit payload through a subprocess, command-line
argument, shell, task definition, or container environment. The OS/runtime
surface is therefore unchanged: in-process Django calls and the existing
PostgreSQL connection are the only write path. The existing archive management
command is a consumer of stored rows and is outside the emission port.

## Enforcement evidence required from the implementation

The same package set and direction must be covered by all of these incumbents:

- `.importlinter` root packages and contracts;
- `scripts/check_layer_imports/layer_imports.yaml` and
  `scripts/check_layer_imports/check_layer_imports.py`;
- `scripts/adr_guard/adr_guard.py` checks for layer imports and direct
  cross-layer model imports;
- `management.management.commands.check_model_fks`;
- `.pre-commit-config.yaml`, `.github/quality-path-filters.yaml`, and the
  architecture jobs in `.github/workflows/_quality.yml`;
- focused tests under `scripts/check_layer_imports/tests`,
  `scripts/adr_guard/tests`, `tests/management`, and Django config/settings
  tests.

Tests must prove set equality, not just name today’s eight packages: all tracked
local AppConfigs are classified; all installed local apps are classified; stale
classification entries fail; `risk_register` and `config` are scanned by import
and model checks; and adding an unclassified local app to `INSTALLED_APPS`
fails. Import tests also pin the allowed composition exceptions and reject
`shared -> feature`, emitter `-> risk_register.models`, private facade, and
unclassified-package cases.

Guardrail changes update ADR-001 and the ADR enforcement documentation in the
same implementation change. The full architecture gate, import-linter, Ruff,
format, model-boundary command, focused checker tests, and any workflow lint
required by touched files must pass without a new exception or soft-fail.

## Gotchas and anti-patterns

- Do not hide upward imports behind lazy imports, string imports, Django app
  lookup, `TYPE_CHECKING`, a re-export, or a generic service locator. Dependency
  direction is semantic, not merely what a regex can see.
- Do not make `shared` own risk-register authorization policy. Move
  cross-domain controllers to `config` and call the risk domain's public policy
  service; otherwise the audit fix leaves the other `shared -> risk_register`
  leak intact.
- Do not expose `AuditLog.Action`, `EntityType`, or `ActorType` as the emitter
  contract, duplicate them in `shared`, or let the model and contract drift.
- Do not move the AuditLog model/app label/table or edit historical migrations.
- Do not create per-domain audit DTOs, validators, exception classes, writers,
  health probes, or request-IP parsers. Extend the single shared vocabulary and
  event contract when a genuinely new event appears.
- Do not accept arbitrary `HttpRequest`, provider claims, exception objects, or
  model instances in durable state. Shape and redact at the owning call site.
- Do not turn all audit writes strict or all writes best-effort. That would
  either break normal product operations on telemetry failure or weaken the
  fail-closed identity/role controls.
- Do not allow every import from `config` because it is the composition root;
  enumerate wiring and adapter seams narrowly.
- Do not count only literal `INSTALLED_APPS = [...]` entries while ignoring
  conditional `.append()` calls, and do not silently skip an unresolved dynamic
  expression.
- Do not classify the retired `documentation` directory or reintroduce the
  in-app docs surface; ADR-038 is authoritative.

## Non-goals and implementation boundaries

- No runtime code, guardrail, schema, migration, or tracker state is changed by
  this preflight.
- No redesign of risk CRUD, audit retention/archive, audit read permissions,
  API-token semantics, request-id format, proxy topology, or ECS schema.
- No new audit storage backend, broker/outbox, asynchronous delivery guarantee,
  cross-service protocol, or plugin system.
- No cleanup of unrelated legacy migrations or all cross-domain orchestration.
- Issue #530 must be closed as superseded by #1523 or rewritten to a genuinely
  uncovered boundary. It must not retain “add CTF enforcement” as its contract:
  CTF is already present in import and model-boundary enforcement. Tracker
  mutation is a GitHub workflow action, not a repository code change.
