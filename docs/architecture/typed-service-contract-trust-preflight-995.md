# Typed Service Contract Trust Preflight (#995)

Status: pre-implementation guidance

Date: 2026-09-03

Issue: GitHub #995, "refactor: trust typed service-boundary contracts; drop
defensive re-validation in the presentation layer"

This is requirement-free maintenance. The GitHub issue is the shipping
contract. This note fixes the boundary classification for the implementation;
it is not an implementation plan.

## Decision And Scope

Presentation and composition code must consume a first-party service result as
the service's declared return union. It must not add a second `isinstance`,
`getattr` fallback, parser, or shape validator for alternatives the producer
cannot return. For `cms.services.get_active_range`, the authoritative result is
`RangeContext | None`: `RangeContext` and each `InstanceContext` are constructed
and validated inside CMS before the public facade returns.

This applies to both current presentation consumers:

- `mission_control.context_processors.active_range`, including the terminal
  tier; and
- `config.api_dashboard._range_summary`, the composition-root dashboard read.

`mission_control.api.ranges.CurrentRangeView` already demonstrates the intended
trust boundary: it branches on the declared `None` outcome and otherwise uses
the `RangeContext` directly.

Trusting the service result does **not** remove validation of data entering the
service or data arriving from an external system. The boundary classification
is:

| Value | Authoritative gate | Consumer obligation |
| --- | --- | --- |
| persisted `RangeInstance` fields and `range_spec` JSON | CMS query/ownership rules plus `InstanceContext` / `RangeContext` Pydantic construction | Let invalid persisted state fail at the service boundary; do not parse it again in presentation. |
| `get_active_range(...)` result | public `cms.services` signature and producer | Handle `None` and declared/reachable service failures; otherwise trust `RangeContext`. |
| channel-layer receive result | external Channels/Redis transport | Verify the unique probe message, timeout, and missing-layer cases before declaring readiness. A local `Protocol` is typing, not proof that an external round trip succeeded. |
| HTTP/template output | DRF serializers, Django escaping, `json_script`, and the coarse health renderer | Preserve bounded projection, escaping, and error-envelope rules; service typing is not response redaction. |

Consequently, the correlation comparison in
`config.health_checks._round_trip`, the `get_channel_layer() is None` guard, and
the bounded timeout are real transport/readiness checks and remain in scope as
incumbents to preserve, not impossible service-output defenses to delete.

No new ADR is required. ADR-001 already owns cross-layer service access and
ADR-019 already owns the boundary-mock policy. This note clarifies how those
rules meet at a typed first-party return versus an external transport port.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #995 |
| --- | --- | --- |
| active-range ownership/query | `cms.services.get_active_range`, `authorized_range_workspace_ids`, `RangeInstance.objects` | Keep actor-derived workspace filtering, source filtering, soft-delete semantics, ordering, and public-facade access in CMS. No presentation ORM access or private service import. |
| projection validation | `shared.schemas.RangeContext`, `InstanceContext`, and `cms.services._common._instance_contexts_from_range_spec` | Construct once in CMS. Do not add a presentation DTO, `model_validate`, cast, or duplicate field checks. |
| active-range consumers | `CurrentRangeView` direct consumption, `active_range`, and `_range_summary` | Branch only on the declared optional outcome. Preserve each consumer's existing bounded output. |
| instance visibility | `shared.range_visibility.filter_visible_instances` | Keep authorization-sensitive visibility policy after lookup and before template/API projection; contract trust must not bypass it. |
| context fail-soft behavior | `_empty_active_range_context`, `_safe_active_range`, `_nav_active_range` | Keep authenticated page rendering fail-soft for reachable service/persistence failures. One fallback branch is sufficient; do not add exception-type-specific return shapes. |
| dashboard fail-soft behavior | `config.api_dashboard` summary serializers and advisory 200 response | Keep the bounded `{present, status}` shape and independent degradation of range/event summaries. Do not return a raw `RangeContext`. |
| readiness | `django-health-check`, `ChannelLayerRedisHealthCheck`, `_probe_configured_channel_layer`, `_round_trip`, `CoarseHealthCheckView` | Preserve conditional Redis registration, bounded transport round trip, generic public status, and the existing registry. No second health framework or probe DTO. |
| channel config | `config._channels`, `config._redis`, `config.settings`, `config.apps.PortalConfig.ready` | Keep backend selection and TLS/AUTH/CA validation at composition startup. Do not infer health posture from an ad hoc setting or Redis-host heuristic in presentation. |
| errors and logging | module loggers, `shared.log_sanitize`, `shared.errors`, `shared.api.errors`, `config.logging.ECSFormatter` | Server-log operational failures and keep browser/public responses bounded. Do not add a contract-violation exception hierarchy or expose raw exception text. |
| testing | real ORM/service behavior, the channel-layer transport port, ADR-019 baseline ratchet | Seed real rows and replace only real DB/framework/transport boundaries when necessary. Do not patch `cms.services.get_active_range` to return an impossible object or raise a synthetic internal error. |

## Cross-Cutting Security And Runtime Path

The intended change must continue to pass every existing gate below.

1. **Authentication and authorization.** Django authentication supplies
   `request.user`; the API path retains
   `IsAuthenticatedSessionOrApiToken`/Mission Control actor policy. CMS applies
   the active source, soft-delete, workspace membership, and
   `WorkspaceOperation.READ_RANGE` filters. Removing a return-type check must
   not move or duplicate any of those policies in presentation.
2. **Persistence and shape validation.** `RangeInstance` remains CMS-owned.
   Stored status and `range_spec` values cross their runtime validation boundary
   when CMS creates `ResourceStatus`, `InstanceContext`, and `RangeContext`.
   Pydantic validation errors and database/authorization-query failures are real
   service failures; they are not alternative successful return shapes.
3. **Presentation and response safety.** The CTF instance-visibility policy,
   `build_connection_urls`, `_terminal_instances_payload`, Django template
   escaping/`json_script`, dashboard serializers, and
   `CurrentRangeResponseSerializer` remain the bounded output seams. A typed
   service result does not authorize fields for a browser response.
4. **Error envelopes and observability.** Context processors keep the shared
   empty payload on a reachable lookup failure so a global template dependency
   does not turn a degraded range read into a site-wide 500. Dashboard summaries
   remain advisory and independently fail closed. Public APIs continue through
   `shared.api.errors`; `/health` continues through `CoarseHealthCheckView`.
   Detailed failures stay in structured server logs; raw database, Pydantic,
   Redis, hostname, DSN, secret-reference, and stack details do not enter a
   response.
5. **Configuration and secret handling.** This issue adds no env variable or
   setting. Redis selection and TLS/AUTH/CA shape remain owned by
   `config._channels` and `config._redis`. `entrypoint.sh` continues to hydrate
   Redis credentials from provider secret storage through stdin/environment;
   the secret is not placed in process argv, logs, health messages, or response
   bodies.
6. **External transport validation.** The Redis health probe sends a unique
   message through the configured Channels layer, requires the same message
   back, and is timeout-bounded. Its failure is normalized to the installed
   `django-health-check` `ServiceUnavailable` contract and sanitized logging.
   This validation is mandatory precisely because Redis/Channels is outside the
   trusted first-party service boundary.
7. **Host and orchestrator exposure.** `/health` and `/health/` are consumed by
   the Docker `HEALTHCHECK`, AWS ALB/ASG health, GCP/Kubernetes readiness and
   liveness probes, the installation health contract, and stack smoke. Health
   semantics, paths, status codes, and coarse body are unchanged by #995.

## Test Contract

- Drive `active_range`, the dashboard endpoint, and `CurrentRangeView` through
  real CMS queries and real `RangeContext` construction for the present and
  absent outcomes.
- When retaining a fail-soft presentation branch, make it reachable through a
  true input or infrastructure boundary. A malformed persisted range projection
  can exercise CMS's real Pydantic failure path; a database-outage assertion,
  if required, belongs at the database adapter/integration seam. Do not make the
  public service itself the test double.
- Do not add tests for a non-`RangeContext`, non-`None` service result. Such a
  test defines behavior outside the contract and forces first-party topology
  coupling.
- Preserve channel-layer round-trip, missing-layer, timeout/error normalization,
  registration, and coarse-public-body coverage. A hand-written implementation
  of `ChannelLayerProbe` is a valid external-port fake; patching `_probe` or
  `get_active_range` is not.
- Reduce any removed first-party mock entries from
  `scripts/adr_guard/boundary_mock_baseline.json`; never raise the baseline or
  add an ADR exception for this refactor. The checker does not make arbitrary
  `monkeypatch.setattr` good design, so review must apply ADR-019 semantically as
  well as mechanically.

## Extensibility Seam

The extension seam for a new successful active-range outcome is the public CMS
service return contract and its producer. Add a variant there only when the
domain genuinely produces a distinct outcome, then make callers handle the
revised union exhaustively. Do not pre-emptively accept arbitrary objects or add
a presentation-side adapter registry.

For a new external dependency probe, the seam is a narrow transport protocol
like `ChannelLayerProbe`, registered through the existing
`django-health-check` plugin registry and normalized by the existing coarse
health envelope. Timeout/correlation values belong at that transport seam; they
do not belong in `RangeContext` or a generic service-contract framework.

## Whole-Repository Surfaces In Scope

- Service and contracts: `cms.services` public facade,
  `cms/services/_range_queries.py`, `cms/services/_common.py`,
  `shared/schemas/range.py`, `shared/range_visibility.py`, and workspace
  authorization services.
- Presentation/composition: `mission_control/context_processors.py`,
  `mission_control/api/ranges.py`, `mission_control/api/serializers.py`,
  `config/api_dashboard.py`, templates/terminal JSON consumers, and their tests.
- Readiness/config: `config/health_checks.py`, `config/health.py`,
  `config/apps.py`, `config/middleware.py`, `config/_channels.py`,
  `config/_redis.py`, `config/urls.py`, and `entrypoint.sh`.
- Runtime consumers: the portal `Dockerfile`, AWS ALB health-path Terraform,
  GCP/Kubernetes chart and base probes, installation backend health contract,
  `scripts/stack-smoke`, and the Redis integration lane in `Makefile`/Quality CI.
- Enforcement/workflow: ADR-001, ADR-019, `.importlinter`,
  `scripts/check_layer_imports/layer_imports.yaml`,
  `scripts/adr_guard/boundary_mock_baseline.json`, `pyproject.toml` mypy/ruff
  policy, `.pre-commit-config.yaml`, and `.github/workflows/_quality.yml`.

## Gotchas And Anti-Patterns

- Do not replace an `isinstance` check with `getattr`, a cast, `hasattr`,
  dictionary conversion, or a second Pydantic parse. Those preserve the same
  conceptual distrust while hiding it from a text search.
- Do not remove the `None` branch: absence is part of the declared service
  union. Do not conflate absence with a service/persistence failure in logs or
  with a not-ready range in output.
- Do not remove the context/dashboard fail-soft envelope merely because the
  successful return is typed. Database, authorization-query, persisted-data,
  and validation failures remain possible.
- Do not catch `TypeError`, `DatabaseError`, or `ValidationError` separately
  unless the caller has genuinely different behavior for them. Avoid duplicate
  exception hierarchies and duplicate empty payloads.
- Do not move CMS ownership queries, workspace policy, Pydantic construction,
  or range-spec normalization into Mission Control or `config`.
- Do not treat the channel-layer message comparison as redundant return-type
  validation. It is an end-to-end correlation assertion at an external
  transport boundary and protects a routing/replacement readiness signal.
- Do not weaken the public health response, `ALLOWED_HOSTS` admission,
  Redis TLS/AUTH/CA validation, secret hydration, or orchestrator probe
  semantics as collateral cleanup.
- Do not expand this issue into all defensive programming, all broad exception
  catches, all `getattr` uses, or all legacy test doubles in the repository.

## Non-Goals And Implementation Boundaries

- No change to `get_active_range`'s query, authorization, return union, schema,
  persistence model, migration, range lifecycle, source selection, runtime-IP
  overlay, pause/resume capability, or instance-visibility policy.
- No new DTO/schema, parser, validation library, repository, service facade,
  exception family, logging helper, health framework, setting, feature flag, or
  workflow.
- No change to API/template payload shapes, HTTP statuses, WebSocket behavior,
  health endpoint paths/body/status, readiness consumers, Redis configuration,
  secret storage, or process model.
- No broad ADR-019 debt cleanup outside tests directly required to prove #995;
  unrelated dashboard-event and other legacy topology-coupled tests remain
  separate maintenance work.
