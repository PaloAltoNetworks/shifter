# Typed Event Contracts Preflight (#296)

Status: pre-implementation guidance

Date: 2026-07-04

Issue: GitHub #296, "Add TypedDict schemas for SQS/channel layer event
contracts."

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note is intentionally not an
implementation plan.

## Scope Boundary

This is a static typing and contract-clarity change for existing inter-service
events. It must not change event delivery semantics, range lifecycle behavior,
channel-layer authorization, worker acknowledgement, outbox/reconciler
recovery, or websocket payload meaning.

TypedDicts can make handler code and producers easier for mypy to check, but
they are not a runtime trust boundary. Messages still enter from SQS/Pub/Sub or
Django Channels as untrusted dictionaries, so the existing validation and
authorization gates must remain unless they are replaced by one shared parser or
type guard with equivalent behavior.

## Architecture Decisions

- Event wire contracts belong under `shared.messages`, not
  `shared.schemas`. The `shared.schemas` package is the Cyberscript/Pydantic
  DSL compatibility surface for range, request, app, and credential schemas.
  Putting message TypedDicts there would conflate domain schemas with transport
  payloads.
- Keep platform imports going through `shared`. Existing
  `shared.messages.events` currently re-exports Cyberscript event constants and
  models; `shifter_platform` handlers must not start importing
  `cyberscript.messages.events` directly.
- Do not collide with existing Pydantic model names such as
  `RangeStatusUpdatedEvent`, `RangeProvisionedEvent`, and `NGFWEvent`. If
  TypedDicts are added beside them, use names that communicate static payload
  typing, for example a `Payload` or `Dict` suffix.
- Keep SQS/Pub/Sub payload contracts distinct from channel-layer payload
  contracts. Both may live under shared transport modules, but the range status
  event from the durable bus is not the same thing as the `group_send` event
  consumed by `RangeStatusConsumer.range_status`.
- Reflect the current wire shape, not stale examples from the migrated issue.
  In this checkout, `range.provisioned` is notification-only and does not carry
  full instance/subnet/Pulumi state; `range.status.updated` carries
  `request_id`, `range_id`, `user_id`, `new_status`, optional
  `error_message`, and common event metadata where emitted.
- Preserve the handler distinction between permanent malformed payloads and
  transient failures. Permanent invalid/missing/unauthorized payloads may log
  and return so the worker acknowledges them; transient DB, broker, or channel
  failures that must retry must still raise.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #296 |
| --- | --- | --- |
| SNS/SQS envelope parsing | `shared.messages.envelope.parse_sns_message` | Keep this as envelope unwrapping only. Do not make each handler parse SNS envelopes differently. |
| Event constants and model compatibility | `shared.messages.events`, `cyberscript.wire_constants` | Add static payload typing through the shared facade. Do not duplicate event-type strings in handlers. |
| Range status vocabulary | `shared.enums.ResourceStatus` | Continue enum validation before mutating models or broadcasting status. Do not introduce a second status enum or literal-only workflow vocabulary. |
| Durable event recovery | ADR-025, `RangeEventOutbox`, `drain_range_event_outbox`, `reconcile_range_events` | Typing must not weaken transactional outbox, reconciler, retry, DLQ, or ack-after-handler semantics. |
| Worker dispatch and acknowledgement | `shared.management.commands.run_worker`, `config._cloud.QUEUE_CONFIG` / `SQS_QUEUE_CONFIG` | Keep handler paths and delete-after-success behavior stable. |
| Engine projection and audit | `engine.handlers`, `risk_register.services.audit_log_system_event` | Engine remains the owner of `engine.Range` updates and audit rows. CMS or MC must not write Engine state directly. |
| CMS projection and CTF bridge | `cms.handlers.__init__`, `cms.handlers.range_events.apply_range_status`, `cms.handlers.ctf_bridge` | Keep package facade dispatch and atomic status plus bridge behavior intact. |
| Mission Control fanout | `mission_control.handlers`, `mission_control.status_consumers`, `shared.channels.groups`, `shared.schemas.RangeRef` | Websocket fanout remains advisory and uses the existing authenticated consumer and group-name helpers. |
| Logging hygiene | `shared.log_sanitize.safe_log_*`, provisioner `log_redact.safe_log_*`, `config.logging.ECSFormatter` | Do not log raw payloads, queue bodies, provider responses, secrets, or user-controlled error strings without sanitizing. |
| Error envelopes | `shared.api.errors`, `shared.errors` | Background event failures should not leak raw provider or stack details into HTTP/websocket user messages. |
| Import boundaries | `.importlinter`, ADR index, `AGENTS.md` shared/cyberscript rule | Platform layers use `shared` facades; only `shared` imports Cyberscript directly. |
| Typecheck and lint workflow | `shifter/shifter_platform/pyproject.toml`, provisioner `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/_quality.yml` | Mypy is enforced. Do not add broad ignores, weaken CI, or hide type errors behind `Any`. |
| Tests | `tests/engine/test_handlers.py`, `tests/cms/test_handlers.py`, `tests/mission_control/test_handlers.py`, `tests/mission_control/consumers/test_range_status_consumer.py`, `shifter/engine/provisioner/tests/test_events.py`, Cyberscript wire canaries | Keep behavior tests driving real domain rows/channel behavior where practical; type-only changes still need runtime contract coverage for parser/type-guard behavior if added. |

## Cross-Cutting Layers The Design Must Pass

- Auth and authorization surface: SQS worker handlers are internal, but event
  payloads still carry user and range identifiers. Preserve Engine ownership
  checks in `_resolve_authorized_range`, CMS `RangeInstance.user_id` checks,
  Mission Control `RangeRef` validation, and websocket `connect()` auth in
  `mission_control.status_consumers`. TypedDict annotations are not permission
  checks.
- Secret-handling surface: event payloads stay notification-shaped: IDs,
  statuses, bounded error text, and serial metadata where already present. Do
  not add credentials, presigned URLs, DB connection data, full instance state,
  subnet inventory, queue URLs, or cloud provider responses to events or logs.
- Env-binding shape: no new environment configuration should be needed for a
  typing-only issue. If a future validation helper needs dispatch metadata, it
  must build on `config._cloud.QUEUE_CONFIG`, `RANGE_EVENTS_TOPIC_ID`, and the
  existing queue identifiers instead of handler-local `os.environ` reads.
- Config validators: `config._channels` remains the channel-layer backend
  posture gate and `config._cloud` remains the queue/event binding gate.
  TypedDict work must not bypass `CHANNEL_LAYER_BACKEND`, Redis fail-closed
  behavior, cloud-provider queue adapters, or worker handler configuration.
- Message validation surface: inbound code must continue through
  `parse_sns_message`, event-type dispatch, shared event constants, and
  `ResourceStatus` validation. If the implementation removes ad hoc
  `isinstance()` checks, a shared type guard or parser must keep equivalent
  missing-field and wrong-type handling at the boundary.
- OS/process exposure: message payloads must not be moved into process argv,
  shell strings, Kubernetes Job command arrays, or plain environment variables.
  This issue should stay within Python typing and handler annotations.
- Error-envelope surface: malformed internal events should be logged with
  bounded operational detail and then handled according to worker semantics.
  Do not surface raw event bodies or exception text through DRF responses,
  templates, or websocket messages.
- Persistence surface: this issue should not add tables or persistence. If a
  future runtime-validation result is persisted, ADR-025 outbox rules apply:
  first-class model/migration, retention, idempotency, replay, and bounded
  error storage.
- Observability surface: keep existing logger names and structured fields so
  worker, outbox, reconciler, and channel-layer logs remain searchable. Do not
  trade operator-visible warnings for silent casts.

## Extensibility View

The extension point is the transport payload family, parameterized by
`event_type` and transport:

- durable bus payloads: `range.status.updated`, `range.provisioned`,
  `range.destroyed`, `range.cancelled`, `ngfw.event`;
- channel-layer payloads: `range.status`, `ngfw.status`;
- common metadata: `event_id`, `timestamp`, and correlation/request IDs where
  the current producer emits them.

The next likely variation is adding another consumer or event type. That should
require adding one shared payload type and one shared parser/type guard, then
annotating producer and consumer call sites. It should not require re-editing
every handler to duplicate shape checks or event strings.

## Whole-Repo Scope

Likely implementation touch points are:

- `shifter/shifter_platform/shared/messages/events.py`
- possibly `shifter/shifter_platform/shared/messages/__init__.py`
- possibly a shared channel payload module under `shifter/shifter_platform/shared/channels/`
- `shifter/shifter_platform/engine/handlers.py`
- `shifter/shifter_platform/cms/handlers/__init__.py`
- `shifter/shifter_platform/cms/handlers/range_events.py`
- `shifter/shifter_platform/cms/handlers/ngfw_events.py`
- `shifter/shifter_platform/mission_control/handlers.py`
- `shifter/shifter_platform/mission_control/status_consumers.py`
- `shifter/engine/provisioner/events.py` only if producer return types are
  brought into the enforced provisioner mypy estate without importing Django
  `shared`
- targeted handler, consumer, provisioner event, and wire-contract tests

Canonical configs and scripts that will see the artifact:

- `.importlinter`
- `scripts/adr_guard/adr_guard.py`
- `shifter/shifter_platform/pyproject.toml`
- `shifter/engine/provisioner/pyproject.toml`
- `.pre-commit-config.yaml`
- `.github/workflows/_quality.yml`
- `.ground-control.yaml` and `.gc/plan-rules.md`
- `docs/adr/index.yaml` and `docs/adr/exceptions.yaml` if any guardrail or
  exception changes are introduced

## Gotchas And Anti-Patterns

- Do not create `shared/schemas/events.py`; it would duplicate the existing
  message-contract surface and confuse transport payloads with Pydantic domain
  schemas.
- Do not use the migrated issue's `RangeProvisionedEvent` example as the
  current contract. The active producer and handler treat `range.provisioned`
  as notification-only.
- Do not rename existing Pydantic event classes or break imports from
  `shared.messages.events`.
- Do not replace runtime validation with `typing.cast()` at an untrusted
  boundary unless equivalent shape checks remain immediately before the cast.
- Do not turn `parse_sns_message` into a domain validator that knows every
  event. Envelope parsing and event payload validation are separate concerns.
- Do not duplicate `ResourceStatus`, event constants, channel group name
  helpers, exception classes, logging sanitizers, or worker retry logic.
- Do not catch every handler exception just to satisfy a TypedDict narrow.
  Transient correctness failures must still reach SQS/Pub/Sub retry and DLQ.
- Do not add first-party internal mocks only to prove annotations. Prefer
  behavior tests, parser/type-guard tests, and existing cloud/channel boundary
  seams.
- Do not broaden platform layers to import Cyberscript directly. Use shared
  facades from `shifter_platform`; keep any provisioner-side typing compatible
  with the provisioner's standalone package boundary.
- Do not add a changelog fragment for a docs-only preflight note. The eventual
  implementation should decide whether its user-visible or CI-visible behavior
  requires one under `changelog.d/`.

## Non-Goals

- No implementation in this preflight note.
- No new broker, queue, worker, outbox, reconciler, public API, auth flow,
  exception hierarchy, status enum, or validation framework.
- No behavior change to range lifecycle, NGFW lifecycle, CTF bridges, Mission
  Control websocket authorization, channel-layer backend selection, queue
  configuration, or worker acknowledgement.
- No migration of existing Cyberscript Pydantic event models unless the
  implementation deliberately scopes and tests that compatibility work.
