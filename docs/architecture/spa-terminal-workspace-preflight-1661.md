# SPA Terminal Workspace Preflight (#1661)

Status: pre-implementation guidance

Date: 2026-07-27

Issue: GitHub #1661, "SPA Mission Control: multi-device terminal workspace
(tabs/split layouts) parity with legacy"

Requirement: none. The issue title, body, and acceptance criteria are the
shipping contract.

This note fixes the architecture boundary for terminal-workspace parity. It
does not implement routes, components, transports, persistence, or tests, and
it is not an implementation plan.

## Scope And Decisions

- The SPA workspace owns layout, target selection, accessible connection state,
  and non-sensitive browser preferences. It does not own target authorization,
  range readiness, SSH credentials, Guacamole tokens, durable session state,
  or terminal capacity policy.
- `/mission-control/terminal/` is the workspace route. It already has a stable
  Django route name, shared-navigation entry, SPA-host/legacy fallback, and
  rollback behavior. `/mission-control/terminal/:instanceUuid/` remains a
  compatible deep link that selects a member of the current workspace; it must
  not remain a second Mission Control terminal product.
- The workspace inventory comes from the existing
  `useCurrentRange()`/`CurrentRangeResponse` read. It must use the returned,
  actor-filtered `RangePresentation.instances`; it must not query engine models,
  construct a second instance DTO, or add a workspace endpoint.
- The workspace opens xterm SSH only when the canonical range projection is
  ready. Loading, no-range, non-ready, failed-read, empty-target, and stale
  deep-link states are first-class UI states. The backend remains authoritative
  even when a client readiness check passes.
- "SSH" in this workspace means the existing xterm plus
  `/ws/terminal/<instance_uuid>/` path. It does not mean the Guacamole SSH
  protocol. Guacamole SSH remains valid for the existing InstanceTable, CTF,
  and NGFW callers, but adding it as a second SSH implementation inside each
  workspace pane would conflate two access channels and two session-state
  models.
- RDP remains the existing server-brokered Guacamole **new-tab handoff**. Each
  pane exposes the same RDP action and the same preparing/error treatment, but
  the Guacamole client is not embedded in an iframe or treated as an xterm
  pane. This matches the legacy handoff without weakening browser policy.
- Tabs and split are a closed presentation union: `"tabs" | "split"`. Tabs
  enumerate every console-capable current-range instance and show one SSH
  surface. Split shows exactly two independently selected, side-by-side SSH
  surfaces. When at least two targets exist, the two split selections must be
  distinct; do not create two sockets to the same target just to fill both
  slots.
- Do not eagerly connect every instance. One tabs slot or two split slots are
  the resource budget; replacing a slot or leaving the workspace must execute
  `Terminal`'s existing socket/listener/xterm cleanup. This avoids turning one
  page view into an unbounded terminal-session and Secrets Manager burst.
- Persist only bounded, non-secret presentation preferences. Reuse the legacy
  `terminal-layout`, `terminal-active-tab`, `terminal-left-pane`, and
  `terminal-right-pane` keys so SPA/legacy rollback is coherent. Reads and
  writes fail soft when storage is unavailable. Layout values are allowlisted;
  stored UUIDs are accepted only when they are members of the current visible
  target set. Invalid/stale values fall back deterministically to tabs, then the
  first target and (when present) the second distinct target.
- No new ADR is required while the work remains inside ADR-013, ADR-029, and
  ADR-036. Embedding Guacamole, changing CSP, adding a layout framework, or
  changing terminal runtime placement would require a separate decision and
  issue scope.

## Existing Contracts To Reuse

| Concern | Canonical incumbent | Guardrail for #1661 |
| --- | --- | --- |
| Workspace route and IA | `mission_control/urls.py`; `frontend/src/router.tsx`; `frontend/src/features/mission-control/routes.ts`; `frontend/src/app/nav.ts` | Add the missing client index behavior at the existing terminal path. Preserve the per-surface SPA flags and legacy fallback; do not add another route namespace or navigation entry. |
| Active-range inventory | `mission_control.api.ranges.CurrentRangeView`; `CurrentRangeResponseSerializer`; generated `CurrentRangeResponse`, `RangePresentation`, and `InstancePresentation`; `useCurrentRange()` | Reuse the current actor-filtered active-range projection and TanStack Query key. Do not copy response interfaces or fetch in a component. |
| Target visibility and identity | `shared.range_visibility.filter_visible_instances`; instance UUID; existing `InstanceTable.isConsoleCapable` distinction | A route/storage UUID is only an initial selection after membership reconciliation. Keep NGFW app-id access on the NGFW surface; do not pass an NGFW row through the range-instance terminal/Guacamole path. |
| SSH rendering and protocol | `frontend/src/features/mission-control/Terminal.tsx`; `mission_control.routing`; `SSHConsumer`; `engine.services.connect_terminal`; `engine.ssh.SSHConnection` | Reuse one `Terminal` implementation and its exact input/resize/output framing. Do not copy websocket, clipboard, close-code, or xterm setup logic into workspace panes. |
| Terminal state and errors | `useTerminalConnectionState`; `TerminalPage` close-code copy; `shared.enums.WebSocketCloseCode` | Panes may compose the incumbent state hook/copy, but must not create another close-code enum or exception vocabulary. Unknown codes stay generic. |
| Live range reconciliation | `useRangeStatusSocket`; `missionControlKeys.currentRange`; current-range transient polling | Status sockets remain advisory and invalidate the canonical read. A range leaving READY or a target disappearing must tear down affected terminal surfaces. |
| Terminal admission/capacity | `TerminalSessionRegistry`; `terminal_executor`; `config/_terminal_settings.py`; terminal capacity preflights #847/#930 | Keep connection count bounded by visible workspace slots and surface close code 4503 as retryable user action. Do not auto-reconnect multiple panes in lockstep. |
| RDP workflow | `useGuacamoleSession`; `useRequestGuacamoleUrl`; `mission_control.api.guacamole`; `mission_control.guacamole_session`; `mission_control.guacamole_bootstrap`; `mission_control.guacamole` | A pane owns its own busy/error state but reuses the single queue/poll/open implementation with `protocol: "rdp"`. Never copy the poll loop or mint/parse Guacamole auth in React. |
| API/schema boundary | `frontend/src/api/client.ts`; `queryClient.ts`; `errors.ts`; generated `schema.d.ts`; DRF serializers | `/api/v1/`, same-origin credentials, CSRF, request IDs, generated response types, bounded GET retry, and mutation no-retry remain canonical. Layout state is UI state, not an API schema. |
| Browser persistence | `frontend/src/lib/theme.ts`; legacy `TerminalManager.loadLayoutPreference()` and terminal layout tests | Use a feature-local guarded adapter over the established keys. Do not add a global client store, persist server state, or put signed URLs/terminal data in storage. |
| UI/accessibility | `components/ui/tabs.tsx`; `select.tsx`; `button.tsx`; `alert.tsx`; `card.tsx`; `PageHeader` | Reuse Radix-backed tabs/selects and the shared design system. Layout controls need names, focus behavior, keyboard operation, non-color status text, and responsive fallback. |
| Observability | `SSHConsumer` session audit; `shared.audit`; Guacamole bootstrap logs/duration; `shared.log_sanitize`; `X-Request-ID` | Existing server boundaries already log/audit access outcomes. Do not add client logging for layout changes or log terminal frames, signed URLs, credentials, or raw errors. |

## Cross-Cutting Layers The Design Must Pass

### Authentication, authorization, and target policy

- The page remains behind the existing authenticated Mission Control route
  handle and Django session. That route gate is advisory UI policy, not access
  authorization.
- The terminal WebSocket still passes
  `AllowedHostsOriginValidator(AuthMiddlewareStack(CTFAccountWebSocketBoundary(
  URLRouter(...))))` in `config/asgi.py`. It uses the same-origin Django session;
  the SPA must not add bearer tokens, query-string credentials, CORS, or a
  second websocket handshake.
- `SSHConsumer` checks authentication, applies process/per-user admission, and
  delegates ownership, active-range, READY-state, declared-channel, instance,
  host, key-reference, and SSH host-key policy to
  `engine.services.connect_terminal()`/`get_ssh_connection_info()`.
- Guacamole POST/status calls keep
  `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, and
  `mission-control:guacamole:read`; status delivery remains scoped by both
  bootstrap id and owner. Browser calls use the session and CSRF path in
  `apiFetch`, never a browser-held `shf_` token.
- A deep-link, localStorage, or select value is untrusted presentation input.
  Reconcile it with the current API inventory before rendering a `Terminal` or
  invoking Guacamole. Do not duplicate backend UUID/ownership validation with a
  client regex or treat a hidden/disabled control as authorization.

### Shape validation and parsers

- `CurrentRangeResponseSerializer` and the shared `RangeContext` projection are
  the server response contract; `schema.d.ts` is the client contract. No
  workspace DTO or duplicate instance schema is warranted.
- `GuacamoleInstanceSerializer` validates the POST shape; the application
  service and engine resolver validate protocol, target ownership, readiness,
  declared participant channel, OS support, host, and credential availability.
  React must not recreate those rules from `os_type`.
- `SSHConsumer.receive()` owns JSON parsing and dispatch for the existing
  `input` and `resize` frames. `Terminal.bindSocket()` owns defensive parsing
  and shape-checking of `output` frames. The workspace only composes
  `Terminal`; it does not add a second message parser.
- Browser preference parsing is intentionally small: allowlist two layout
  strings and intersect stored target ids with the current visible instance
  set. Storage failure or malformed values must not block terminal access.

### Secrets and browser security

- Session/CSRF cookies, SSH private keys, host keys, RDP passwords, Guacamole
  JSON-auth secrets, signed Guacamole URLs/tokens, terminal input/output, and
  raw provider errors must not enter React state beyond the minimum existing
  in-memory handoff, localStorage/sessionStorage, URL/query/hash state, logs,
  analytics, screenshots, test snapshots, or error copy.
- Guacamole token construction and exchange stay in
  `mission_control.guacamole`; credentials remain just-in-time engine secret
  reads. The owner-scoped status endpoint atomically consumes and clears the
  parked signed URL once.
- `config/_browser_security.py` is the single CSP authority under ADR-036. Its
  reviewed policy has `frame-src 'none'`, and production Portal responses also
  use `X_FRAME_OPTIONS = "DENY"`. RDP new-tab handoff requires no exception.
  An iframe would require an explicit CSP/Guacamole framing threat review and
  is outside #1661; report-only deployment is not permission to build against a
  policy that enforcement will block.
- React renders instance names/IPs as text. Do not reintroduce the legacy
  `innerHTML` construction or an HTML-escaping helper in the SPA.

### Configuration, runtime, and OS exposure

- No new environment binding is needed. Existing
  `PLATFORM_SPA_ENABLED`/`MISSION_CONTROL_SPA_ENABLED`, terminal `TERMINAL_*`
  bounds, `GUACAMOLE_BASE_URL` (browser path),
  `GUACAMOLE_API_BASE_URL` (server-to-server path), Guacamole bootstrap
  settings, and `BROWSER_CSP_MODE` keep their current parsers and
  `config/env-manifest.json` ownership.
- The workspace is static browser code and must add no shell command, helper
  process, temp file, SSH subprocess, Terraform/Kubernetes value, or secret
  delivery path. Nothing from a terminal or Guacamole session belongs in
  process argv or environment variables.
- A two-pane layout does not justify Golden Layout, Split.js, a second xterm
  package, public-CDN assets, or another Vite entry point. CSS grid/flex plus
  the existing Radix primitives cover the accepted layout.
- `Terminal` currently sizes and refits itself around a fixed-height container
  and window resize. Workspace sizing must stay behind the `Terminal`
  component boundary: make its container size parent-controllable and refit on
  real container visibility/size changes (for example via `ResizeObserver`).
  Do not leak `FitAddon` or xterm DOM ownership into the workspace layout.

### Errors, retries, cleanup, and observability

- Canonical DRF reads use the shared nested API error envelope and `ApiError`.
  Guacamole bootstrap/status retains some flat legacy `{"error": "..."}` bodies;
  `useGuacamoleSession` is the compatibility boundary. Do not add a workspace
  exception class or expose raw backend/provider text to compensate.
- TanStack Query may retry idempotent reads according to `queryClient.ts`.
  Guacamole bootstrap mutations are not auto-retried. Terminal reconnect
  remains an explicit per-pane action using the existing close-code mapping;
  do not create an automatic multi-pane reconnect storm.
- Every target/layout change and component unmount must close the replaced
  WebSocket, dispose xterm listeners/addons, cancel pending callbacks, and
  release Guacamole UI state. A Guacamole poll started by a pane must not open a
  browser tab after that pane/workspace unmounts; if cancellation is added, add
  it once to the shared opener using `apiFetch`'s `AbortSignal` seam so every
  caller gets identical behavior. Server-side work may finish and expire/prune
  normally. React Strict Mode tests must not leave duplicate sockets, polls, or
  listeners.
- The asynchronous Guacamole `window.open()` can be popup-blocked. Any
  detection/current-tab fallback improvement belongs in the shared
  `useBootstrapOpener` path so Mission Control, CTF, and NGFW do not diverge.
  The fallback must not persist or log the already-consumed signed URL.
- Existing terminal connect/disconnect audit and Guacamole bootstrap outcome
  logs are sufficient. Client layout/selection telemetry is not required.

## Extensibility Seam

The only new seam needed is a small, typed workspace view model:

- layout mode: the closed `"tabs" | "split"` union;
- inventory: canonical `InstancePresentation` values from the current range;
- assignments: active tab plus left/right instance UUIDs, always reconciled
  against that inventory;
- rendering slot: one reusable SSH `Terminal` surface with per-slot
  connection/reconnect state and RDP action;
- persistence adapter: the established localStorage keys with allowlist and
  stale-target normalization.

This leaves a clean future boundary for #316: an advanced layout renderer may
replace the two-mode assignment renderer without changing `Terminal`,
Guacamole bootstrapping, current-range schemas, authorization, or error
handling. If that future work changes the persisted shape, it must version and
migrate the feature-local preferences rather than reinterpret old values.

## Whole-Repo Scope For The Follow-Up

- Governing architecture: ADR-013, ADR-029, ADR-036;
  `docs/architecture/spa-mission-control-workspace-preflight-1370.md`;
  terminal capacity notes #847/#930; Guacamole token lifecycle/affinity notes
  #928/#939/#991.
- SPA routing and IA: `frontend/src/router.tsx`,
  `features/mission-control/routes.ts`, `app/nav.ts`, and their tests.
- SPA workspace and primitives:
  `features/mission-control/{Terminal,TerminalPage,InstanceTable,guacamole}.tsx`
  or `.ts`, a feature-local workspace surface, `components/ui/{tabs,select}`,
  and focused Vitest/Testing Library coverage.
- Canonical reads/errors: `frontend/src/api/{mission-control,client,errors,
  queryClient,types,schema.d.ts}`. Backend/OpenAPI changes are not expected.
- Server security/transport incumbents to regression-check, not redesign:
  `config/{asgi,websocket_auth,_browser_security,_terminal_settings,
  _guacamole_settings}.py`; `mission_control/{routing,consumers,
  terminal_sessions,terminal_executor,guacamole_session,guacamole_bootstrap,
  guacamole}.py`; `mission_control/api/{ranges,guacamole,serializers}.py`;
  `engine/services/_terminal.py`; `shared/range_visibility.py`.
- Legacy parity/rollback evidence:
  `templates/mission_control/terminal.html`,
  `static/js/{terminal,terminal-layout,terminal-guacamole}.js`, and their tests.
  The SPA must not import or execute these assets.
- Required repository gates for touched implementation surfaces: frontend
  typecheck/build, ESLint, Vitest, relevant Playwright coverage, API schema
  drift checks when schemas change, and ADR guard. Python import-linter and
  stack-native infrastructure checks apply only if those surfaces are actually
  changed.

## Gotchas And Anti-Patterns

- Do not render the standalone `TerminalPage` once per instance and call that a
  workspace. The workspace must own shared range inventory, layout, target
  reconciliation, and per-slot lifecycle while reusing `Terminal`.
- Do not fetch the active range once per pane, create a workspace API, hand-copy
  `InstancePresentation`, or derive access capability from names, roles, or OS.
- Do not conflate xterm SSH, Guacamole range SSH, NGFW SSH, and RDP because they
  all display a console. They have different transports, identifiers, capacity,
  ownership checks, and error lifecycles.
- Do not pass route/storage values directly to a websocket or Guacamole call;
  normalize them against the actor-filtered current range first.
- Do not open N sockets during render, keep replaced split targets alive,
  create duplicate sockets for the same split target, or bypass terminal
  session caps to make the UI appear connected.
- Do not copy terminal socket framing, close-code mappings, Guacamole polling,
  CSRF handling, API errors, instance schemas, or status enums into new files.
- Do not put signed Guacamole URLs into component state, anchors, browser
  storage, history, query cache, logs, toasts, or test snapshots.
- Do not broaden CSP `frame-src`, add a route-specific CSP override, relax
  `X-Frame-Options`, or assume current report-only mode makes iframe embedding
  acceptable.
- Do not install Golden Layout/Split.js or build draggable/dockable/arbitrary-N
  panels under this parity issue. A fixed two-column split is the contract.
- Do not rely only on `window.resize` to fit xterm after a tab, select, shell,
  or grid-size change; hidden/zero-width xterm containers are a known failure
  mode.
- Do not use color alone for active/connected/disconnected state, hide focus
  outlines, or make tab/select/button labels depend only on icons.
- Do not persist range data, terminal output, connection status, errors, or
  Guacamole state. Browser preferences are disposable and never authoritative.

## Non-Goals And Implementation Boundaries

- No Guacamole iframe, in-pane RDP client, Guacamole auth redesign, durable
  Guacamole connection rows, or direct browser-to-guacd connection.
- No new terminal protocol, gateway, websocket route, authentication scheme,
  capacity model, retry framework, audit table, or exception hierarchy.
- No CTF terminal-workspace expansion and no NGFW access-flow merge. Shared
  incumbents may improve centrally, but their product routes remain distinct.
- No advanced Golden Layout docking, arbitrary pane counts, saved workspace
  documents, cross-device preference sync, or server-side layout persistence.
- No range lifecycle, provisioning, instance visibility, participant-channel,
  secret-store, cloud networking, Terraform, Kubernetes, or deployment change.
- No retirement of the legacy Django terminal route or its assets; route
  retirement remains a separate ADR-029 migration decision.

## Preflight Validation

For this documentation-only preflight:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```
