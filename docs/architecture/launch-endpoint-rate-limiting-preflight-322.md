# Launch Endpoint Rate-Limiting Preflight (#322)

Status: pre-implementation guidance

Issue #322 is the contract. It covers backpressure for the user-initiated range
and NGFW launch endpoints; it does not define a Ground Control requirement.

## Boundary and decisions

- Enforce admission at the authenticated Mission Control DRF boundary, before
  serializers call CMS. Both legacy `/mission-control/api/...` routes and
  canonical `/api/v1/mission-control/...` routes already dispatch through
  `LaunchRangeView` and `NGFWCreateView`; do not add parallel decorators to the
  retired private Django implementations.
- Apply two independent controls per operation: an actor budget prevents one
  user from repeatedly launching, while a fleet budget caps accepted launch
  pressure across users. A per-user limit alone does not prevent a many-user
  cascade; a fleet-only limit lets one actor consume everyone else's budget.
- Identify the actor with
  `mission_control.api.permissions.mission_control_actor_user`. DRF's stock
  `UserRateThrottle` is not sufficient because API-token authentication sets
  `request.user` to `None` and carries the owning user in `request.auth`.
- Keep range and NGFW budgets separately named and configurable. They have
  different downstream costs and must not share an accidental counter merely
  because both are called “launch”. The durable extension seam is an operation
  policy containing actor capacity/window and fleet capacity/window.
- Production admission state must be shared across portal workers and replicas,
  using the existing Redis host/auth/TLS/CA posture. Admission must consume a
  token atomically; DRF's non-atomic history-cache throttles and a
  read-then-write counter can over-admit exactly during the burst this issue is
  meant to contain. Local-memory state is acceptable only for tests or an
  explicitly single-process development runtime.
- A Redis/admission failure must not silently disable launch protection. Fail
  closed for these two expensive mutations with a bounded 503 and
  `Retry-After`; readiness should already expose a configured cache dependency.
  Reads, lifecycle cleanup, and unrelated mutations must remain available.
- Return HTTP 429 with `Retry-After` when a budget is exhausted. Preserve the
  canonical `shared.api.errors` envelope and
  `MissionControlAPIView.handle_exception` legacy flat envelope; do not create
  a CMS/domain exception for a transport admission decision.
- Do not persist a new launch DTO, request schema, or business audit row for a
  rejected request. Redis admission state is ephemeral operational state;
  accepted launches continue to use the existing CMS `Request`,
  `RangeInstance`, `Instance`, and `App` records and their existing audit path.

## Canonical incumbents to reuse

| Concern | Incumbent and guardrail |
| --- | --- |
| Route convergence | `mission_control/views/__init__.py::_api_view`, `mission_control/api/urls.py`, and `mission_control/urls.py`; cover both URL families through the same DRF view classes. |
| Authentication/authorization | `IsAuthenticatedSessionOrApiToken`, `HasMissionControlActor`, `_range_write_permission`, `_ngfw_write_permission`, and `block_participant_lifecycle_permission("launch")`; throttling runs only after these gates and never substitutes for them. |
| Request validation | `LaunchRangeSerializer`, `NGFWCreateSerializer`, `_extract_ngfw_create_payload`, CMS `_validate_*` helpers, scenario launchability, credential ownership/type checks, and shared Pydantic request/spec schemas remain authoritative. Do not duplicate their shape checks in the limiter. |
| Service boundary | `cms.services.create_range_dispatch` and `cms.services.create_ngfw`; the limiter admits calls to these services but must not move hydration, active-resource rules, persistence, dispatch, or auditing into the view. |
| Error envelopes | DRF `Throttled`/`APIException`, `shared.api.errors.api_exception_handler`, and `MissionControlAPIView.handle_exception`; retain canonical/legacy compatibility and `X-Request-ID`. |
| Redis posture | `config/_channels.py`, `entrypoint.sh`, `REDIS_HOST`/`REDIS_PORT`/`REDIS_TLS`/`REDIS_PASSWORD`/`REDIS_CA_MODE`/`REDIS_CA_PEM`, GCP runtime rendering, AWS SSM/user-data, and the existing Redis network policies. Reuse or narrowly extract this connection-shape validation; do not build a second plaintext or unauthenticated client configuration. Use a distinct key namespace (and logical DB where supported) from Channels. |
| Edge protection | `platform/terraform/modules/portal/alb/main.tf` WAF rate rule remains coarse per-IP abuse protection. It is additive, not the authenticated launch budget: NAT, multiple tokens, non-AWS ingress, and operation cost make the concepts different. |
| Adjacent throttles | `ctf.views._access._check_invite_rate_limit` is the fixed-window/cache precedent; CTF submission cooldown and `ctf.services.range.batch` pacing remain CTF domain/workflow policy. Do not import CTF-private helpers or conflate those policies with Mission Control admission. |
| Logging/audit | Existing Mission Control/CMS loggers, `safe_log_value`, request IDs, and `risk_register` audit services. Rejections need bounded operational visibility, not one durable audit write per denied attempt. |
| Capacity visibility | `config.capacity_metrics` and the low-cardinality `Shifter/PortalCapacity` conventions if metrics are added. Admission outcome/operation/reason are safe dimensions; actor, token, email, IP, request body, scenario, credential, and request UUID are not metric dimensions. |

## Cross-cutting security and runtime layers

- **Edge and host validation:** preserve ALB/Cloud Armor/ingress, WAF, TLS,
  `ALLOWED_HOSTS`, CSRF for session requests, and API-token fail-closed
  authentication. Anonymous or invalid credentials remain governed by those
  layers; do not key an authenticated budget by spoofable forwarded headers.
- **Actor and scope policy:** session users and bearer tokens for the same owner
  consume the same actor budget. Existing range/NGFW write scopes and the CTF
  participant launch block run before admission. A limiter result grants
  capacity, never authorization.
- **Input shapes:** admission reads only the resolved actor and the view's fixed
  operation name. Body parsing and field validation stay in the existing DRF
  serializers; scenario, agent, credential, registration, CMS, Pydantic, and
  Engine validators remain unchanged.
- **Secret handling:** reuse the Redis secret hydration path. Never put the
  password, CA PEM, bearer token, cookie, OTP, SCM PIN, authcode, or a
  credential-bearing Redis URL in a cache key, ConfigMap, log, metric, response,
  process argv, or generated runtime file.
- **Environment/config shape:** policy defaults belong in a single validated
  Django settings mapping. Any environment overrides are non-secret, must fail
  startup on malformed/non-positive rate or window values, and must flow
  through the env manifest plus the canonical AWS/GCP runtime binding paths if
  a deployment owns them. Do not parse policy strings lazily on the first
  launch request.
- **OS/process/network exposure:** non-secret rate values may be environment
  variables; Redis credentials remain stdin/secret-store hydrated rather than
  shell arguments. Preserve TLS certificate verification and existing Redis
  egress ports/CIDRs; do not broaden NetworkPolicy or security groups to make a
  new client work.
- **Error leakage:** 429 responses expose only a stable safe message and wait
  duration. Cache failures expose no host, URL, backend exception, key, or
  policy internals. Logs use operation, outcome/reason, bounded wait, request
  ID, and sanitized internal actor ID only.

## Reliability, tests, and observability guardrails

- Token consumption must be atomic across processes, with deterministic lock or
  key ordering if actor and fleet budgets are checked together. Do not consume
  one budget and leak that token when the other rejects unless that conservative
  behavior is explicit and tested.
- Define whether a token is charged before body validation. The safe default for
  endpoint backpressure is to charge every authenticated POST reaching the
  expensive endpoint, including malformed attempts; document and test it.
- Test session and API-token actors, legacy and canonical URLs, range and NGFW
  budget independence, actor and fleet exhaustion, concurrent requests,
  `Retry-After`, canonical and legacy envelopes, cache outage behavior, and
  recovery after the window/refill. Prove rejected requests never call CMS or
  write launch/audit records, and that destroy/cancel/read endpoints are not
  throttled.
- Emit one bounded structured rejection/failure log or low-cardinality metric;
  do not log every successful token check. Alarms should distinguish exhausted
  budgets from an unavailable admission backend.
- UI clients may display the existing safe error and retry hint, but must not
  automatically synchronize retries at the reset boundary. Jitter any future
  automated retry behavior.

## Gotchas and anti-patterns

- Process-local `LocMemCache`, per-pod counters, and DRF's stock non-atomic
  throttle history can pass unit tests while over-admitting in production.
- The existing active-range/active-NGFW checks are business invariants, not
  rate limits, and are themselves vulnerable to concurrent check-then-create
  races. Do not claim this issue fixes that separate uniqueness problem unless
  the implementation deliberately adds transactional enforcement.
- Do not sleep in the request, queue launches implicitly, hold a database
  transaction across Engine/cloud dispatch, or retry provisioning from the
  limiter. Rejection is backpressure; queueing and workflow orchestration are
  different contracts.
- Do not key by raw email, token, cookie, IP, request payload, scenario, agent,
  credential, or secret. Do not let a client choose the operation/scope name.
- Do not reuse CTF exception classes, CTF cooldown fields, invitation cache
  keys, WAF counters, portal in-flight gauges, worker queues, or CMS `Request`
  rows as if they were interchangeable admission state.
- Do not weaken authentication, CSRF, API scopes, Redis AUTH/TLS/CA validation,
  health checks, NetworkPolicy, WAF, logging sanitization, serializer validation,
  CMS ownership checks, or Engine schemas to land the limiter.

## Non-goals

- No general API-wide throttling policy, anonymous login throttling, upload or
  lifecycle throttling, CTF event pacing change, worker queue redesign, or
  provisioning scheduler is part of #322.
- No change to launch request/response DTOs beyond the standard 429/503 error
  contracts; no duplicate exception hierarchy, repository, launch service,
  schema, audit workflow, or persistence model.
- No promise that rate limiting makes active-resource check-then-create logic
  unique or idempotent. That concurrency invariant should be handled separately
  at the CMS persistence boundary.
- No WAF/Cloud Armor parity project, Redis topology migration, or autoscaling
  redesign. Infrastructure edits are needed only if the shared cache contract
  is not already bound in a supported runtime.

Because this change stays within existing DRF, CMS, Redis, and error-envelope
boundaries, no new ADR is required. A new durable launch queue, public API
contract, cross-service admission service, or provider-specific bypass would
require a separate architecture decision.
