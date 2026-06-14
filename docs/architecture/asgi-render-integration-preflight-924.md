# ASGI and Render Integration Test Preflight (#924)

Status: pre-implementation guidance

Date: 2026-06-14

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/924>

## Scope Boundary

Issue #924 is a verification-stack change. It adds evidence for two event-load
paths that are currently under-tested:

- browser websocket paths through the real portal ASGI application and channel
  layer, and
- authenticated HTML page renders through the real Django template/context
  stack with numeric query budgets.

This is requirement-free work. The GitHub issue is the source of truth. The
implementation must not redesign ASGI routing, websocket protocols, terminal
authorization, notification semantics, context processors, page templates, or
the channel-layer posture contract merely to make tests easier.

## Architecture Decisions

- Use `config.asgi.application` as the only ASGI application under test. The
  evidence must pass through `ProtocolTypeRouter`,
  `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, and the registered
  Mission Control, experiment, and shared websocket routing.
- A websocket integration test that manually writes `communicator.scope["user"]`
  or `communicator.scope["url_route"]` is not real-stack evidence. It is a
  consumer-level test. Real-stack tests should authenticate through Django's
  session cookie and provide allowed `Host` / `Origin` headers so the existing
  auth and origin gates decide the scope.
- Keep channel-layer posture explicit. Redis-backed tests should set
  `CHANNEL_LAYER_BACKEND=redis`, `REDIS_HOST`, and `REDIS_PORT` before the
  ASGI/settings surface is built, and should fail loud if that posture cannot
  be established. In-memory tests should use the documented
  `CHANNEL_LAYER_BACKEND=in_memory` posture.
- Do not globally move the whole platform test suite onto Redis. The existing
  default test ergonomics are in-memory unless a targeted integration slice
  opts into Redis.
- `WebsocketCommunicator` alone is same-process evidence. If a test claims
  multi-process or cross-worker notification delivery, it must actually use
  isolated processes or workers that both import the real ASGI/channel-layer
  stack. Two communicators in one event loop do not prove that property.
- Redis is the only posture where cross-process fan-out is expected to succeed.
  The in-memory posture can prove same-process websocket behavior and explicit
  non-event posture, but it must not be described as event-representative
  multi-process delivery.
- Terminal websocket tests must keep authorization in
  `engine.services.connect_terminal()` / `get_ssh_connection_info()` and SSH
  mechanics in `engine.ssh.SSHConnection`. If interaction is exercised with a
  loopback SSH server, patch only process/network/cloud SDK boundaries; do not
  patch `SSHConsumer`, `connect_terminal`, `SSHConnection`, or `render`.
- Page-render query budgets must use `django.test.Client` plus
  `CaptureQueriesContext` around the actual request/response render. The
  existing mocked view-topology tests remain useful unit tests, but they are not
  query-budget evidence.
- Query budgets should be numeric, named by page/scenario, and kept in test
  code as the executable contract. Do not use broad "current plus slack"
  assertions or comments in place of failing numbers.
- No new ADR is needed for this verification work. A new ADR/design decision is
  needed only if the implementation introduces a new runtime topology,
  channel-layer contract, metrics framework, auth exchange, schema, or public
  diagnostic surface.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #924 |
| --- | --- | --- |
| ASGI application | `shifter/shifter_platform/config/asgi.py` | Import and test the existing `application`; do not create a test-only router or settings module. |
| Websocket auth/origin | `AllowedHostsOriginValidator`, `AuthMiddlewareStack`, Django session cookies | Let middleware build `scope["user"]`; do not inject authenticated users into consumer scope for real-stack tests. |
| Websocket routes | `mission_control/routing.py`, `cms/experiments/routing.py`, `shared/routing.py` | Use public websocket paths such as `/ws/terminal/<uuid>/` and `/ws/notifications/`; do not call consumers directly. |
| Channel-layer config | `config/_channels.py`, `config/settings.py`, ADR-018 docs | Use `CHANNEL_LAYER_BACKEND` and `_build_channel_layers`; do not create a parallel Redis fixture/config parser. |
| Channel-layer readiness | `config/health_checks.py`, `/health` docs for #477/#919 | Keep readiness semantics separate from fan-out integration tests; do not redefine cache health in the ASGI suite. |
| Terminal authorization | `engine/services/_terminal.py` | Reuse range ownership, readiness, instance lookup, and secret-reference checks. |
| SSH transport | `engine/ssh.py` | Use `asyncssh` mechanics; no SSH CLI, temp key files, or subprocess wrappers for terminal interaction tests. |
| Terminal capacity | `mission_control/terminal_sessions.py`, `TERMINAL_*` settings | Assert per-process caps and cleanup honestly; do not imply a global cap unless a shared store is introduced by a separate issue. |
| Notifications | `shared/notifications.py`, `shared/consumers.py`, `shared/channels/groups.py` | Reuse registration, topic validation, subscription authorization, persistence, replay, and hashed group names. |
| Websocket close codes | `shared.enums.WebSocketCloseCode` | Assert enum values or names; do not introduce numeric literals outside established tests. |
| Page render path | `mission_control.views._pages`, `ctf.views`, `config/settings.py` template context processors | Exercise real `render()` through `Client`; do not patch `mission_control.views.render` in query-budget tests. |
| Context/query ownership | `mission_control.context_processors`, `shared.context_processors`, `ctf.context_processors`, `cms.services`, `ctf.bridges` | Reuse existing role, range, and permission services; no duplicate DTOs or role/group validators. |
| Test boundaries | ADR-019 and `scripts/adr_guard/boundary_mock_baseline.json` | New tests may patch process/network/cloud SDK/framework transport boundaries only; first-party internal patch debt must not grow. |
| CI/test workflow | `.github/workflows/_quality.yml`, `pyproject.toml` pytest settings | Add Redis only to the targeted platform integration evidence path and keep xdist-sensitive tests isolated. |

## Cross-Cutting Layers

- Auth surface: HTTP page tests enter through Django middleware,
  `AuthenticationMiddleware`, login/session state, and CTF decorators.
  Websocket tests enter through session cookies under `AuthMiddlewareStack`.
  Test fixtures may create users/groups/profiles, but the request path must not
  bypass these gates by manually assigning request or websocket users.
- Host/origin surface: websocket tests must satisfy
  `AllowedHostsOriginValidator` with allowed `Host` and `Origin` headers. Do not
  weaken `ALLOWED_HOSTS` or use wildcard host/origin settings for tests.
- Authorization and validation surface: terminal access is validated by engine
  services; range-status access by CMS services; notification access by
  `authorize_subscription()` and `validate_topic()`; CTF page access by CTF
  decorators/services; CMS authoring links by `shared.auth`. Tests should seed
  the required domain state and assert behavior after these validators run.
- Secret-handling surface: Redis passwords, CA PEM, DB credentials, session
  cookies, private SSH keys, Guacamole URLs, and cloud secrets must not be
  printed, placed in process argv, committed as fixtures, uploaded as artifacts,
  or logged in assertion diagnostics. Test private keys may be generated at
  runtime and kept in memory; if a secret-store boundary is stubbed, target the
  cloud SDK/process boundary rather than first-party service functions.
- Env-binding surface: `CHANNEL_LAYER_BACKEND`, `REDIS_HOST`, `REDIS_PORT`, and
  `REDIS_TLS` are the channel-layer contract. `DJANGO_SECRET_KEY`, `TESTING`,
  and database env stay with the existing platform test job. Invalid Redis
  posture must fail closed through `config._channels`, not be caught and
  downgraded in a fixture.
- Config validators: `DJANGO_SECRET_KEY`, field encryption key defaults in test
  mode, OIDC session refresh bypass fixtures, Redis TLS password/CA validation,
  and Django template context registration must remain active. Do not suppress
  settings import failures or monkeypatch validators away.
- OS/process exposure: multi-process tests must pass only non-secret knobs in
  env/argv. They must account for process-local terminal session registries,
  Redis connections, DB connections, websocket FDs, SSH sockets, and pytest
  worker isolation. Stateful ASGI/Redis tests should not run under uncontrolled
  `xdist` parallelism.
- Network exposure: Redis in CI should be bound to the GitHub Actions service
  network/localhost for the test job only. Loopback SSH servers, if used, stay
  on localhost and random free ports. Do not broaden Terraform, Kubernetes, or
  Docker Compose network posture for test convenience.
- Error-envelope surface: browser-facing websocket failures should continue to
  use `WebSocketCloseCode`; HTTP pages and APIs should continue using existing
  authored responses/classifiers. Test failure output may include sanitized route
  names, close codes, and query counts, not raw exception text with secrets.
- Observability surface: use existing ECS-style application logging and sanitized
  identifiers. Integration tests may assert non-secret startup posture fields
  or aggregate counts, but should not scrape or expose Redis URLs, session
  cookies, terminal payloads, SSH bytes, or full SQL with sensitive literals.
- Persistence surface: tests may create normal Django rows for users, sessions,
  ranges, notifications, and CTF state. Do not add migrations, audit tables,
  replay schemas, or durable measurement tables for this issue.
- Workflow surface: touching `.github/workflows/**` is guardrail work. Run
  ADR guard and `actionlint`, and keep the workflow change limited to the Redis
  service/env needed for the targeted integration evidence.

## Extensibility Seam

The durable seam is an evidence matrix, not a new runtime abstraction:

- websocket path: terminal, range/status if covered, and notifications;
- channel-layer posture: `in_memory` and `redis`;
- process topology: same-process communicator and explicit multi-process worker
  harness where cross-worker delivery is claimed;
- page scenario: authenticated Mission Control dashboard, terminal, active-range
  or participant range page, and representative CTF participant pages;
- budget row: route name/path, fixture shape, numeric query budget, and whether
  active range / CTF role / notification state is present.

Future pages or websocket topics should add rows to that matrix without
rewriting ASGI routing, channel-layer config, terminal authorization, shared
notification schemas, or context processor contracts.

## Gotchas

- Import timing matters. Django settings and Channels layer managers cache
  configuration. Backend posture changes should be process-isolated or use one
  canonical fixture that rebuilds/clears the Channels layer safely.
- `WebsocketCommunicator` against `SSHConsumer.as_asgi()` is still valuable, but
  it is not evidence for `config.asgi.application`, origin validation, routing,
  or auth middleware.
- The terminal session registry is process-local by design. A reconnect-storm
  test must assert cleanup for the process under test; it must not imply a
  cross-process global cap.
- Abnormal websocket close coverage must still wait for cleanup paths to run
  before asserting registry counts, audit rows, or Redis group state.
- Notification fan-out has both live channel-layer delivery and persisted replay
  semantics. Test both intentionally if both are in scope; do not treat replay
  as proof of live cross-worker delivery.
- Query budgets are sensitive to fixture setup, auth session creation, lazy
  context processors, and CTF group/profile lookups. Capture only the request
  under test, after setup and login are complete.
- A lazy object is not proof of fewer queries if common sidebars touch it on
  every page. Budget tests must exercise fully rendered templates.
- CI already uses `pytest-xdist` by default. Redis-backed stateful tests need a
  deterministic isolation story such as a targeted `-n 0` command, unique Redis
  prefixes/topics, or process-local cleanup.

## Anti-Patterns

- Creating a second ASGI app, URL router, Redis settings module, notification
  registry, terminal DTO, role schema, error hierarchy, logging formatter, or
  query-budget framework.
- Bypassing `AllowedHostsOriginValidator`, session auth, CTF decorators,
  context processors, or Django templates to make tests faster.
- Growing first-party internal mocks for `render`, `connect_terminal`,
  `get_active_range`, `get_user_role`, notification publishers, model helpers,
  or consumer methods.
- Treating in-memory Channels as evidence for multi-process event fan-out.
- Sending terminal input/output through shared notification groups or Redis
  channel-layer groups.
- Logging terminal streams, private keys, signed Guacamole URLs, session
  cookies, Redis auth URLs, DB credentials, or raw environment dumps.
- Making query budgets advisory, snapshot-only, or hidden in documentation
  instead of executable failing assertions.
- Weakening ADR guard, import-linter, actionlint, Ruff, or CI service health
  checks to land the suite.

## Non-Goals

- No implementation, production code rewrite, ASGI routing change, channel-layer
  posture change, worker model change, or deployment topology change in this
  preflight.
- No new Ground Control requirement; issue #924 remains the authoritative
  contract.
- No new metrics framework, public diagnostic endpoint, cache policy, schema,
  migration, audit model, notification protocol, terminal protocol, or auth
  exchange.
- No decision to replace Guacamole, split terminal traffic into a separate
  service, add a global terminal cap, or make Redis mandatory for all local and
  unit tests.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Implementation follow-ups must also run the stack-native checks for changed
surfaces: from `shifter/shifter_platform`, `uv run ruff check .`,
`uv run ruff format --check .`, targeted pytest suites for
`tests/integration/asgi/` and `tests/integration/mission_control/`, and
`uv run lint-imports --config ../../.importlinter` if Python imports change.
If workflow files are touched, also run `actionlint`.
