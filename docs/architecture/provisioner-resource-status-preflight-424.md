# Provisioner Resource Status Preflight (#424)

Status: pre-implementation guidance

Date: 2026-07-21

Issue: GitHub #424, "Provisioner uses magic strings for status instead of
ResourceStatus enum."

This issue is requirement-free. The GitHub issue is the shipping contract.
This note records the current repository decision and boundary guardrails; it
is not an implementation plan.

## Scope Boundary

Provisioner-owned range and NGFW lifecycle values must come from the existing
`cyberscript.enums.ResourceStatus` contract. At persistence and wire boundaries,
use its string value or the existing `STATUS_*` aliases in
`shifter/engine/provisioner/events.py`, which are derived from that enum.

The migrated issue's `ready` versus `active` question is no longer open.
Migrations `engine/0016_normalize_ngfw_statuses.py` and
`engine/0017_normalize_ngfw_app_statuses.py` established one vocabulary across
Engine and CMS:

| Legacy NGFW status | Canonical `ResourceStatus` |
| --- | --- |
| `active` | `READY` (`ready`) |
| `stopped` | `PAUSED` (`paused`) |
| `stopping` | `PAUSING` (`pausing`) |
| `starting` | `RESUMING` (`resuming`) |

Do not add `ResourceStatus.ACTIVE` or retain a separate NGFW lifecycle enum.
`READY` means the materialized resource is running and available whether it
arrived there through initial provisioning or resume. The operation and the
transition (`provisioning` or `resuming`) carry provenance; the steady state
must not encode how it was reached.

## Architecture Decisions And Guardrails

- `cyberscript.enums.ResourceStatus` remains the sole provisioner lifecycle
  vocabulary. `shifter_platform` code continues to import it only through
  `shared.enums`; the standalone provisioner may use its existing direct
  Cyberscript dependency.
- Reuse the provisioner `events.py` `STATUS_*` aliases at call sites instead of
  creating module-local constants or another enum. Add an alias there only when
  an existing `ResourceStatus` member lacks one.
- The status value written to `engine_instance`, `engine_app`,
  `mission_control_range`, and the transactional outbox must be identical to
  the value emitted in the corresponding lifecycle event. Keep the existing
  persist-plus-event helpers and atomic outbox path; replacing literals must
  not split or reorder those effects.
- `ngfw_runtime_ops._validate_ngfw_operation` is the canonical operation-to-
  transition seam. Start maps to `RESUMING -> READY`; stop maps to
  `PAUSING -> PAUSED`. Provider implementations consume that mapping rather
  than defining AWS- or GCP-specific lifecycle values.
- Status comparisons, idempotency guards, retry convergence checks, and SQL
  lifecycle predicates are part of the same contract as writes. They must use
  the canonical values too. SQL values remain DB-API parameters; do not
  interpolate enum values into query strings.
- Preserve exact wire strings. `ResourceStatus` is a `StrEnum`, but explicit
  `.value`/`STATUS_*` strings at JSON and psycopg boundaries keep serialization
  and database behavior unambiguous.
- This issue does not justify changing event shapes, handler routing, model
  fields, migration history, exception types, logging fields, or lifecycle
  ordering.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail |
| --- | --- | --- |
| Lifecycle vocabulary | `shifter/cyberscript/enums.py:ResourceStatus` | No `ACTIVE`, NGFW-specific enum, `Literal` clone, or duplicated status set. |
| Provisioner status constants | `shifter/engine/provisioner/events.py:STATUS_*` | Use the aliases already sourced from `ResourceStatus`; do not add local aliases. |
| NGFW operation transitions | `shifter/engine/provisioner/ngfw_runtime_ops.py:_validate_ngfw_operation` | Keep one provider-neutral start/stop mapping. |
| Privileged launch admission | `engine.launch_intents.validate_provisioner_command` / `authorize_provisioner_payload`, Engine lifecycle services | Preserve UUID/command shape checks, operation-generation checks, ownership correlation, and allowed-state admission; its NGFW allowed-state map must stay aligned with `ResourceStatus`. |
| NGFW persistence | `ngfw_runtime.update_instance_state`, `range_ops._update_ngfw_status` | Preserve synchronized Instance/App writes and existing transaction behavior. |
| Range persistence plus event intent | `provisioner_db.update_range_status(..., outbox_event=...)` and `events.build_status_event` | Status and outbox intent remain atomic. |
| Durable event contract | `cyberscript.messages.events`, `cyberscript.wire_constants`, provisioner `events.py` | Do not invent another DTO or event type. |
| Platform import facade | `shifter_platform/shared/enums.py` and `shared.messages` | Platform layers must not import Cyberscript directly. |
| ORM compatibility choices | `engine.models.Range.Status` | This existing Django `TextChoices` projection must stay wire-aligned; it is not a second provisioner source of truth. |
| Inbound status validation | CMS range/NGFW handlers using `ResourceStatus(value)` | Static typing or enum-backed producers do not replace validation of untrusted messages. |
| Persistence projections | Engine/CMS models, handlers, and migrations `0016`/`0017` | Do not reintroduce legacy values or add a migration for a constant-only cleanup. |
| Recovery and ordering | ADR-025 outbox/reconciler behavior and `cms.management.commands.reconcile_range_events` | Preserve retry, idempotency, forward-progress, and DLQ behavior. |
| Logging hygiene | provisioner `log_redact.safe_log_*`, platform `shared.log_sanitize.safe_log_*`, existing logger namespaces | Log status and bounded identifiers, not full payloads, state, credentials, or provider responses. |
| Tests | Cyberscript/provisioner wire canaries and provisioner lifecycle behavior tests | Assert enum-derived values at persistence/event seams and retain failure/idempotency coverage. |

## Cross-Cutting Layers The Design Must Pass

- **Command/auth surface:** authenticated Mission Control/CMS entrypoints and
  Engine lifecycle services enforce ownership and admissible source states;
  `engine.launch_intents` then validates the canonical command shape, UUID,
  operation generation, target, and current state before privileged dispatch.
  `main.py` admits NGFW operations through argparse choices, and
  `run_ngfw_operation` validates the operation again before any write. Keep
  every gate. This cleanup adds no authorization path and must not let a status
  value become caller-supplied.
- **Message shape and validation:** lifecycle notifications continue through
  the existing event builders, transactional outbox, shared SNS/SQS envelope
  parser, event-type routing, and CMS `ResourceStatus(value)` validation before
  CMS mutation. Typed dictionaries are static-only and are not a replacement
  for the runtime trust boundary. Engine's NGFW notification/audit consumer
  must not become a new NGFW status writer as part of this issue. The Engine
  range projection currently trusts its statically cast payload while CMS and
  Mission Control perform enum validation; enum-backed producer call sites do
  not close that pre-existing inbound-validation gap. Do not add another
  handler-local validator under this issue, and do not claim the gap is solved;
  shared runtime event parsing is separate follow-up scope.
- **Ownership checks:** range event consumers retain range/user correlation and
  ownership checks. NGFW notification identifiers retain their existing
  request/instance/app correlation. Enum cleanup must not bypass these checks
  or change which component owns the authoritative database write.
- **Persistence:** direct provisioner writes continue to use psycopg parameters
  and the existing transactions. Range status plus outbox intent stays atomic;
  NGFW Instance/App status stays synchronized. No schema change is needed—the
  canonical strings already fit and migrations have normalized legacy rows.
- **Secret handling:** status values are non-secret. No credential, secret
  reference contents, full state JSON, provider response, or raw event body is
  added to a payload or log. Existing secret stores and redaction helpers are
  untouched.
- **Environment/config shape:** no environment variable, settings binding,
  queue configuration, provider configuration, or validator changes are
  required. Continue using `RANGE_EVENTS_TOPIC_ID`/the existing topic fallback
  through `events.py`; do not add status configuration through environment
  variables.
- **OS/process exposure:** operation and request ID remain the only relevant CLI
  inputs. `engine.launch_intents` persists a versioned, secret-free command;
  AWS ECS and local development dispatch use argument lists rather than a
  shell, while the GCP ValidatingAdmissionPolicy fixes the entrypoint and
  allowlists the argument shape. Local mode carries its existing database
  credentials in the child environment, not argv. Statuses are internal
  constants and must not be added to process argv, Kubernetes command arrays,
  or environment variables.
- **Exceptions and error envelopes:** preserve `ValueError` for unsupported
  operations, existing runtime/provider exception propagation, worker retry
  behavior, and the current public error envelope. Range `error_message` can
  reach the authenticated websocket client, so a touched failure branch must
  keep user-facing text generic and put provider detail only in sanitized
  operator logs. Some existing provisioner paths still derive stored errors
  from `str(exception)`; that is a pre-existing bounding/leakage concern, not a
  reason to expand this enum cleanup or copy the pattern. Do not create a
  status-specific exception hierarchy or expose more raw provider detail.
- **Observability/audit:** preserve event IDs, request correlation, stable
  logger names, status transition logs, and existing audit mapping. Do not log
  complete event or state dictionaries to demonstrate enum use.

## Extensibility View

The extension seam is the provider-neutral operation-to-transition mapping in
`ngfw_runtime_ops`, parameterized by operation. A future lifecycle operation or
provider should reuse a valid `ResourceStatus` transition there, then flow
through the existing persistence and event helpers. One obvious variation must
not require adding provider-specific steady states or editing independent AWS,
GCP, Engine, CMS, and frontend vocabularies.

If lifecycle provenance later matters after a resource reaches `READY`, model
it as operation/audit metadata (the existing operation fields and events are
the relevant seam), not as a second synonym for the steady state.

## Whole-Repository Scope

The implementation must account for current status producers and consumers in:

- provisioner runtime operation, range pause/resume, NGFW Terraform, database,
  event, outbox, retry, and status-query modules;
- Cyberscript enum, event models, schemas, and wire-contract canaries;
- Engine and CMS Instance/App/Range persistence, event handlers, lifecycle
  services, reconciler ordering, and migrations `0016`/`0017`;
- Mission Control/channel/frontend consumers only as compatibility checks—no
  transport or UI behavior change is required.

Canonical enforcement surfaces are the provisioner and platform
`pyproject.toml` files, `.importlinter`, `.pre-commit-config.yaml`, the quality
workflows, `scripts/adr_guard/adr_guard.py`, and the existing targeted
provisioner/Cyberscript/platform tests. No guardrail file or ADR registry change
is warranted unless implementation broadens beyond constant reuse.

## Gotchas And Anti-Patterns

- Do not replace provider-native states such as AWS `pending`/`running`/
  `stopped`, Kubernetes phases, Terraform results, VPN readiness flags, CTF
  event/participant `active`, CSS classes, or outbox delivery status. They are
  different domains that happen to share English words.
- Do not add `ACTIVE` to `ResourceStatus`, preserve `active` as an NGFW alias,
  or make `READY` and `ACTIVE` compare equal. That recreates the ambiguity the
  normalization migrations removed.
- Do not add another schema, DTO, validation function, exception hierarchy, or
  lifecycle helper for this mechanical contract cleanup. Existing Cyberscript
  Pydantic events and `shared.messages.payloads` TypedDicts already own runtime
  producer contracts and static consumer shapes respectively.
- Do not replace runtime message validation with an enum annotation or
  `typing.cast`; inbound queue payloads remain untrusted dictionaries.
- Do not perform blind repository-wide string replacement. Logs, prose,
  provider APIs, tests of external states, and unrelated domains legitimately
  contain these words.
- Do not bypass `events.py`, publish before a durable write, or make a range
  status update and outbox insert separate transactions.
- Do not interpolate enum values into SQL or loosen parameterization to make
  constants easier to use.
- Do not weaken mypy, Ruff, import-linter, ADR guard, or test gates for a
  constant-only change.

## Non-Goals

- No implementation in this preflight note.
- No new lifecycle states, state machine framework, public API, event type,
  broker, worker, repository layer, schema, validator, or exception family.
- No migration rewrite or new data migration; the legacy values were already
  normalized by migrations `0016` and `0017`.
- No changes to provider power-state semantics, pause/resume orchestration,
  retry counts, error policy, event delivery, frontend presentation, auth, or
  secret handling.
- No cleanup of every string that resembles a status outside the provisioner
  resource lifecycle contract.
