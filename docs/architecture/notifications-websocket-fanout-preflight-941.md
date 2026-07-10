# Shared WebSocket Notification Fan-Out Preflight (#941)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/941>

Superseded note: ADR-027 / issue #1195 removed the legacy experiments app and
its direct experiment-status websocket. References below to experiment-specific
websockets, publishers, and tests describe the pre-removal state and are not
current implementation guidance.

## Scope Boundary

Issue #941 is requirement-free maintenance work. The GitHub issue is the
contract: either justify the shared persisted notification websocket with a real
browser consumer, bounded fan-out, and scheduled pruning, or park it behind a
disabled-by-default flag so it has no event-load cost.

At the time this preflight was written, the repository had two different
websocket concepts:

1. Direct feature websockets, such as the experiment status socket at
   `/ws/experiment-status/<experiment_id>/`, which broadcasts live status through
   an experiment channel group and is consumed by the experiment detail template.
2. The shared notification socket at `/ws/notifications/`, which persists missed
   notifications per recipient in `shared_websocket_notification` and replays
   them after topic subscription.

Do not conflate them. The direct experiment socket is a real feature consumer,
but it is not a consumer of the shared persisted notification path. Unless the
implementation introduces an actual browser subscriber for `/ws/notifications/`,
the shared path should be disabled by default.

## Architecture Decisions

- Prefer the park-by-default branch for #941 unless implementation discovers a
  concrete product surface that needs shared persisted browser notifications now.
  A dormant generic notification subsystem is not worth per-recipient writes
  during event traffic.
- Use one non-secret, environment-owned enablement setting, for example
  `WEBSOCKET_NOTIFICATIONS_ENABLED`, defaulting to false. The disabled state must
  stop cost before persistence and fan-out: no `WebSocketNotification` rows and
  no notification `group_send` calls.
- ADR-027 later removed the direct experiment websocket path. Disabling or
  enabling the shared notification path must no longer depend on that deleted
  experiment surface.
- If the enabled branch is chosen, it must reuse the existing shared registry,
  topic validation, authorizers, payload projection, group-name helper,
  close-code enum, model, and prune command. Do not add a second notification
  schema, publisher, route family, exception hierarchy, or validation layer.
- If enabling requires broadcast semantics, bound fan-out at the notification
  service boundary. Per-recipient persisted rows are acceptable only when replay
  is a real requirement for those recipients. Live-only group sends should not
  be forced through per-recipient durable queue rows.
- Pruning already has an application command:
  `python manage.py prune_notifications`. If the notification path is enabled,
  schedule that command through the existing worker/scheduler/container runtime
  conventions, with heartbeat/health behavior where a long-running scheduler is
  introduced. Do not add ad hoc cron logic hidden in a deploy script.
- No new ADR is required for the disable-by-default branch. Add an ADR only if
  implementation introduces a new runtime scheduler, a new cross-process
  delivery model, a new notification persistence contract, or a new public
  diagnostics/observability surface.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #941 |
| --- | --- | --- |
| Shared notification contract | `shifter/shifter_platform/shared/notifications.py` | Reuse `register_notification_type`, `validate_topic`, authorizers, payload handlers, idempotency, replay bounds, and pruning. Gate here or above it so disabled mode does no DB writes. |
| Notification persistence | `shared.models.WebSocketNotification` and migration `shared/migrations/0001_initial.py` | Do not add a duplicate queue table. Remember the model is per recipient and therefore the event-load risk. |
| Shared notification socket | `shared.consumers.SharedNotificationConsumer`, `shared/routing.py` | Keep `AuthMiddlewareStack`, topic authorization, replay, and `WebSocketCloseCode`. Disabled mode should deny or omit this surface without weakening other websocket routes. |
| Group naming | `shared.channels.groups.notification_user_topic_group` / `cyberscript.channels.groups` | Use the hashed topic group helper; do not place raw topic strings into transport group names. |
| Deleted experiment live updates | Removed by ADR-027 | Historical direct feature websocket; do not reintroduce it as a shared-notification dependency. |
| Notification registration | Shared notification registry | Keep app startup deterministic, and make disabled mode no-op before persistence. |
| ASGI stack | `config/asgi.py` | All websocket paths go through `ProtocolTypeRouter`, `AllowedHostsOriginValidator`, and `AuthMiddlewareStack`; do not create a parallel ASGI app or test-only router. |
| Channel-layer posture | `config/_channels.py`, `docs/architecture/portal-channel-layer-backend.md` | Preserve explicit `CHANNEL_LAYER_BACKEND`; do not infer Redis from ASG mode or silently fall back from invalid Redis posture. |
| Runtime settings | `config/settings.py` `_env_bool`, `_env_int` | Add only one flag, parsed through existing helpers. Existing replay and retention settings are not an enablement flag. |
| Runtime env hydration | AWS `platform/terraform/modules/portal/ssm`, `platform/terraform/modules/portal/ec2/user_data.sh`, `scripts/portal-deploy/deploy_portal.sh`; GCP `scripts/gcp/render_runtime_env.py` and k8s/Helm env paths | If deployment-time enablement is exposed, wire the same non-secret flag through the canonical env paths. Do not hard-code it in the image or only one provider path. |
| Scheduled runtime | `shared/management/commands/run_worker.py`, `ctf/management/commands/run_ctf_scheduler.py`, worker/scheduler platform tests | If pruning is scheduled, follow the existing management-command and heartbeat conventions. Do not piggyback shared maintenance work onto CTF-specific task semantics. |
| Logging hygiene | `config.logging.ECSFormatter`, `shared.log_sanitize.safe_log_value` | Logs may carry feature flag state, type, topic, counts, and user ids where already used. Do not log payload bodies, cookies, Redis URLs, DB details, or raw exceptions into browser messages. |
| Error envelopes | `shared.enums.WebSocketCloseCode`, `shared.errors.classify_user_message` for HTTP views | Websocket failures use close codes; HTTP/API errors keep existing user-message classification. Do not add a notification-specific exception hierarchy. |
| Real-stack tests | `tests/integration/asgi/test_notifications_ws.py`, `tests/shared/test_notifications.py` | Update tests around the real ASGI stack and existing publishers. Do not replace them with first-party mocks of notification internals. |

## Cross-Cutting Layers

- Auth surface: shared notification sockets must continue through
  `AllowedHostsOriginValidator` and `AuthMiddlewareStack`, then through
  `authorize_subscription()` and feature authorizers such as
  `_can_subscribe_to_experiment()`. The flag must not bypass auth; when disabled,
  prefer no route or an existing close code such as `SERVICE_UNAVAILABLE`.
- Host/origin surface: browser websocket consumers must satisfy the deployed
  `ALLOWED_HOSTS`/Origin policy. Do not relax host/origin settings to make a new
  notification consumer easier to test.
- Secret-handling surface: notification payloads are browser-visible. Continue to
  project payloads through registered payload handlers before persistence or
  send, and keep credentials, session cookies, upload tokens, Guacamole URLs,
  Redis auth material, DB settings, and stack traces out of payloads and logs.
- Env-binding shape: the enablement flag is non-secret configuration. In Django,
  parse it through `config.settings` helpers. In AWS, if it must be operator
  tunable, publish it as a non-secret SSM `String` and hydrate it through both
  first-boot and SSM redeploy paths. In GCP, render it through the existing
  generated runtime env path. Absent means disabled.
- Config validators: keep the existing fail-loud behavior for `DJANGO_SECRET_KEY`,
  field encryption key, OIDC production settings, and Redis TLS/AUTH posture.
  Notification gating must not catch and downgrade settings import failures.
- OS/process exposure: Docker env and process argv are visible to privileged
  same-host readers, so only non-secret booleans and numeric bounds belong there.
  Do not pass payloads, cookies, Redis URLs, DB credentials, or command bodies on
  argv to schedule pruning or test the feature.
- Error-envelope surface: websocket clients should see bounded close codes and
  authored notification payloads only. They should not receive raw exception
  text, database errors, Redis errors, or Python tracebacks when the subsystem is
  disabled or misconfigured.
- Persistence surface: disabled mode must not create `WebSocketNotification`
  rows. Enabled mode must preserve idempotency on recipient/topic/type/event,
  bounded replay (`WEBSOCKET_NOTIFICATION_MAX_REPLAY`), finite retention
  (`WEBSOCKET_NOTIFICATION_RETENTION_DAYS`), and pruning of expired rows.
- Observability surface: use the existing ECS JSON logging path and sanitized
  values. A non-secret startup or publish-skip log is acceptable if it is
  low-cardinality; do not introduce a metrics framework for this issue.
- Workflow/deploy surface: changes to workflows, Terraform, Kubernetes, Helm, or
  guardrail files must run the repo's native validators. Do not weaken ADR guard,
  import-linter, actionlint, TFLint, kube-linter, kubeconform, or stack-smoke
  checks to land a notification flag.

## Whole-Repo Scope

Likely in scope for implementation:

- `shifter/shifter_platform/shared/notifications.py`, `shared/consumers.py`,
  `shared/routing.py`, and existing notification tests.
- `shifter/shifter_platform/config/settings.py` for the enablement setting.
- `shifter/shifter_platform/cms/experiments/handlers.py`,
  `cms/experiments/notifications.py`, and experiment tests if the shared
  experiment notification publishers are gated.
- `shifter/shifter_platform/config/asgi.py` only if disabled mode omits the
  shared route from the composed ASGI router.
- Deployment env paths only if the flag is made operator-tunable beyond its
  default false behavior: AWS portal SSM/user-data/redeploy, GCP runtime env
  renderer, Kubernetes manifests, and Helm templates.
- Worker/scheduler deployment surfaces only if the enabled branch schedules
  pruning.

Out of scope unless separately accepted:

- Replacing the direct experiment websocket with the shared notification socket.
- Deleting the existing model/migration merely to avoid cost; gating before writes
  is enough for the park branch.
- Redesigning channel-layer posture, ASGI runtime, Redis topology, portal worker
  count, or health checks.
- Adding a generic notification center UI solely to justify the existing
  subsystem.

## Extensibility Seam

The required seam is a single enablement parameter:

```text
WEBSOCKET_NOTIFICATIONS_ENABLED=false
```

That flag answers whether the shared persisted notification subsystem is active
at all. Future legitimate variations should extend the existing registration or
publish contract with explicit delivery policy, for example persisted
per-recipient replay versus live-only topic broadcast, instead of creating a
second publisher or overloading retention values as control flow.

Re-enabling requires all of these to be true:

- a named browser consumer subscribes to `/ws/notifications/` and uses the
  delivered payload;
- the publishing path is bounded for the event shape, with no unnecessary
  per-recipient durable rows;
- `prune_notifications` is scheduled in the deployed runtime; and
- tests cover disabled no-write behavior plus enabled auth, bounded fan-out, and
  pruning.

## Gotchas

- Gating only the route or frontend is not enough. Event handlers would still pay
  the per-recipient DB-write cost unless publishing no-ops before persistence.
- `WEBSOCKET_NOTIFICATION_RETENTION_DAYS` and
  `WEBSOCKET_NOTIFICATION_MAX_REPLAY` are bounds, not an enablement contract.
  Setting retention to zero is not a safe disable mechanism.
- App startup currently registers experiment notification types in
  `ExperimentsConfig.ready()`. Registration alone is cheap, but it can make tests
  look enabled even when publishing is disabled. Tests must assert DB rows and
  channel sends, not just registry contents.
- Existing direct experiment websocket frontend code is already a consumer of
  `/ws/experiment-status/<id>/`. Adding a shared notification frontend on the same
  page can double-deliver status changes unless the implementation deliberately
  chooses one path.
- In-memory Channels is not evidence for event-representative multi-process
  fan-out. Redis posture tests must use the explicit `CHANNEL_LAYER_BACKEND=redis`
  contract and fail closed if Redis is misconfigured.
- Per-recipient idempotency prevents duplicate source-event rows; it does not
  reduce first-delivery storm cost across many recipients.
- `prune_notifications` deletes expired rows. Delivered-but-unexpired rows still
  remain until expiry, so enabling the subsystem needs a retention value that
  matches the product requirement and event DB budget.
- A browser websocket is not CSRF-protected in the same way as POST endpoints.
  Session auth plus allowed Host/Origin and topic authorization are the relevant
  gates here.
- Scheduling pruning in only one deployment path creates drift. Fresh boot,
  redeploy, Docker Compose, AWS, and GCP should either all remain disabled or all
  represent the enabled runtime contract.

## Anti-Patterns

- Creating a second notification model, DTO schema, validator, route family,
  publisher, exception hierarchy, logging formatter, or scheduler DSL.
- Treating the direct experiment websocket as proof that the shared notification
  socket has a consumer.
- Hiding event-load cost behind a frontend-only flag while background handlers
  continue to write durable rows.
- Fan-out by looping over every recipient when a topic/group send satisfies the
  feature and replay is not required.
- Logging notification payloads, cookies, Redis URLs, DB settings, env dumps, or
  traceback text to prove the feature is disabled.
- Adding cron fragments to user-data, deploy scripts, or workflows without the
  repo's worker/scheduler health and deployment parity conventions.
- Weakening channel-layer fail-closed behavior or falling back to in-memory Redis
  posture to make tests pass.

## Non-Goals

- No implementation in this preflight.
- No new Ground Control requirement; GitHub issue #941 is the source of truth.
- No new notification product, inbox UI, browser toast framework, or marketing
  surface unless a separate product issue asks for it.
- No removal of existing migrations, tables, or tests merely as cleanup.
- No redesign of experiment execution, experiment status hydration, SQS event
  handling, ASGI runtime, Redis, portal deployment topology, or worker health.
- No new app-wide metrics or public diagnostics surface for notifications.

## Validation

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

If implementation touches the Django platform code, also run the relevant pytest
slices for shared notifications, experiment handlers/notifications, and ASGI
websocket integration. If it touches deployment/runtime surfaces, run the
stack-native validators required by `AGENTS.md`.
