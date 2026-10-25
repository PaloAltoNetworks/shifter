# Private broker and Engine control preflight — #2122

Architecture guidance for M05 / PLAT-202, inspected at `37f0b11bec2c` on
2026-09-19. This is neither an implementation plan nor runtime qualification.
Apply [ADR-059](../../adr/059-range-model-access-broker.md),
[ADR-060](../../adr/060-model-access-allocation-accounting.md) and
[ADR-061](../../adr/061-model-access-operations-qualification.md), together with
the [architecture](architecture.md), [security](security.md),
[accounting preflight](request-accounting-preflight-2121.md) and current
[source-management contract](source-management.md).

## Baseline and ownership

M05 is not a blank-slate service. This checkout already has `model_broker`,
`engine/model_access_control`, credential persistence, provider transports and
their tests. Complete and harden those boundaries; do not create another proxy,
token service, accounting store, cloud factory or workflow engine. Paths below
are relative to `shifter/shifter_platform/` unless rooted otherwise.

- **Broker:** bounded participant HTTP, provider translation and transport.
  `.importlinter`'s `model-broker-isolation` prohibits application, Django,
  PostgreSQL and Redis imports, including through helpers. The same platform
  image does not give this process the portal's environment or authority.
- **Engine:** grants, current authority, immutable allocations/prices, request
  reservations, dispatch/continuation leases, settlement and reconciliation.
  `engine/model_access_control/server.py` is its private transport facade;
  `engine/services/_model_broker_control.py` composes existing domain services.
  Cross-domain consumers use public service facades and existing owner bridges.
- **CMS/CTF/Workspaces:** scenario needs, event sponsorship and tenant/source-use
  authority remain with their existing services and revision projections.
  Source registration, membership, funded eligibility and permission to invoke
  are different facts; the broker cannot reconstruct them from user claims.
- **Provisioner/SDK:** `shifter/engine/provisioner/model_enrollment.py` and
  `shifter/shifter_adapter_sdk/model_access.py` own guest delivery/refresh.
  Executable scenario adapters consume the published SDK, never provider keys
  or core imports. Keep the existing operation generation; `grant_epoch` and
  source/policy revisions do not introduce new execution generations.

[ADR-064](../../adr/064-default-range-model-access.md) now allows direct keyless
guest invocation as a separate posture. It does **not** supply M05's mandatory
accounting or revocation. Broker-mediated ranges remain identity-less with the
exact admitted broker egress capability. Broker failure, disabled configuration
or a source edit must not silently switch such a range to direct invocation.

## Cross-cutting gates and canonical incumbents

| Layer | Reuse and required boundary |
| --- | --- |
| Participant HTTP and JSON | `shared/model_access/http.py` and `messages.py`: actual socket peer, duplicate/conflicting headers, framing, compression, byte/depth limits, closed Messages/count shapes, alias/capability checks and explicit version/beta policy. Unknown fields cannot become upstream transport options. Bound the HTTP server parser before ASGI as well as application parsing. |
| Private control wire | `engine/model_access_control/schemas.py` uses `ClosedModel`, `BillingBound`, `ProviderUsage` and `SecretStr`; shared `credentials.py` and `provider_runtime.py` own replies crossing processes. Validate replies as well as requests. A shared reply contract belongs under `shared/model_access`, not an Engine import or a separately copied broker schema. |
| Workload authentication | `control_identity.py`, `workload_identity.py`, `model_broker/identity.py` and the control entry point: verified signature, issuer, audience, expiry and exact configured identity; bounded verification I/O. Enrollment has a distinct provisioner identity and operation-bound audience. Broker routes reject provisioner, participant and portal credentials; broker identity cannot enroll. |
| Guest authentication and authorization | `engine/services/_model_credentials.py`, `_model_allocation_authority.py`, the sharing authority projections and `_model_credential_transition.py`: hashed opaque credentials, constant-time checks, locked one-use exchange/refresh, current operation/epoch/authority, trusted subnet and original hard expiry. Do not substitute portal sessions, API tokens or offline JWT grants. |
| Catalog and provider configuration | `catalog.py`, `catalog_v3.py`, `catalog_v4.py`, `runtime.py`, `ProviderInventory`, `ProviderTarget.bind` and `SourceExecutionProjection`: closed versions, verified digests, exact shard/model/principal/credential binding and immutable prices. The installed v3 accounting catalog and allocation-specific v4 source overlay are distinct contracts, not two competing configuration authorities. |
| Installation and env bindings | `shifter/installation/model_access.py`, `model_broker_runtime.py`, `gcp_model_broker.py`, `aws_model_broker.py` and `loader.py`/`render.py` own projection. Preserve priced inventory validation, public CA validation, exact applied-resource readback, private coordinates and the aggregate 96 KiB ConfigMap budget. `config/_model_access_settings.py` reparses the mounted catalog. |
| Secrets and cloud selection | `engine/services/_model_source_control.py` uses `shared.cloud.get_secrets_store`, owned immutable names in `shared/cloud/owned_secrets.py`, and `source_credentials.py`. Cloud reads happen outside row locks, followed by reauthorization. The broker receives only an exact ephemeral `SourceExecutionProjection`; it gets no general secret-store capability. `ProviderCredentials`/`bounded_aws_session` own bounded provider authentication. |
| Provider transport and egress | `ProviderAdapterRegistry`, `ModelProviderAdapter`, `model_broker/providers.py`, `provider_usage.py`, `openai_messages.py`, `egress.py` and `egress_proxy.py`: fixed origins/routes, explicit proxy, TLS hostname verification, pinned public DNS or exact approved AWS endpoint exceptions, bounded parsing and no automatic retry/redirect/fallback. Local tool content is data; it never authorizes remote tool execution. |
| Persistence, audit and recovery | `_model_request_accounting.py`, `_model_request_lifecycle.py`, `_model_request_reconcile.py`, existing Engine models/constraints and worker scheduling: canonical lock order, atomic applicable-account reservations and strict `shared.audit` decision records before dispatch. Settlement/reconciliation retain the original account/price vector. No network I/O under these locks or cache-based financial authority. |
| Errors and telemetry | Reuse `ContractError` and authored codes, `NoBillableEffect`, the broker Messages envelope and the private control envelope. Portal routes retain `shared/api/errors.py`, `ClosedJSONParser` and `ClosedSerializer`; importing those DRF wrappers into the broker violates isolation. Errors must never serialize Pydantic input/context, exception chains, signed headers, source projections or provider error bodies. |
| Host/process boundary | Existing broker `__main__.py` and Helm `command: [python, -m, model_broker]` bypass `entrypoint.sh` secret hydration; control retains normal Engine startup. Allowlisted non-secret env, read-only TLS/HMAC mounts, private pod binding, disabled forwarded-peer trust/access logs and existing container security contexts remain mandatory. No credential in argv, shell interpolation, command output, Terraform state, operation JSON, image layers or crash/support bundles. |

`config/_env_manifest.py` scans Django settings, **not** standalone broker/control
entry points. Regenerate `config/env-manifest.json` for settings changes, but
prove standalone variables through installer-to-Helm-to-process tests. Guest
coordinates additionally cross `engine/ecs/_env.py`'s allowlist and the
provisioner's enrollment validators. Public CA text is not a token. Guest
capabilities travel through the existing pinned SSH stdin channel into private
tmpfs files; they cannot be moved into SSM command payloads or setup metadata.

Whole-repository deployment consumers are `platform/charts/shifter/templates/`
(`model-broker`, `model-access-control`, `model-broker-network`,
`model-provider-egress`, and shared security helpers), Terraform's GCP broker/IAM
modules and AWS portal/EKS modules, `scripts/gcp/render_model_broker.py`,
`render_runtime_env.py`, `prepare_model_broker_overlay.py`,
`probe_model_broker.py`, `verify_running_image_ids.py`, and the existing GCP/AWS
deployment lanes under `.github/workflows/`. Use these paths, not a parallel
manifest or operator script. Check the union of NetworkPolicies: an additive
generic policy must not restore broker/proxy access to private services.
Preserve exact-target invocation IAM, separate workload identities, versioned
TLS/HMAC references, digest-pinned images and rollout/drain ordering. The
`scripts/check_tf_gcp_iam_resource_scope` guard is an incumbent, not a substitute
for effective IAM and source-preservation evidence.

## Semantics that must survive transport changes

- `/v1/models` is optional under the architecture contract; if exposed it is an
  authenticated logical-alias view of the current grant. Participant routes do
  not include `/control/v1/*`, source-management APIs or a generic tool/proxy API.
  Private liveness/readiness responses contain no catalog or credential data.
- Broker `reserve`/`advance` binds token, observed peer, allocation, operation,
  grant epoch and request. Each potentially effective provider call, including
  count-to-invoke transitions, needs current online authority. A control timeout
  means the result may have committed, not that repeating dispatch is safe.
- `finish` deliberately uses workload authority after guest revocation: recording
  an old charge must not require a still-usable participant token. It may settle
  only existing reservations through Engine's closed actions. It cannot enlarge
  limits, change prices, release an uncertain effect or create a new request.
- Cancellation ends broker transport, not necessarily provider execution.
  Unknown usage keeps conservative liability and the existing reconciliation
  obligation. `NoBillableEffect` is only for an adapter-proven absence of a
  billable effect; a timeout or generic provider failure is not that proof.
- Count endpoints need rate/concurrency admission even when priced at zero.
  Free counting is an explicit current provider/pricing assumption, not a
  universal property. Engine prices the bound; caller-supplied charge fields
  cannot authorize spend. Cache/reasoning/tool billing must be covered by the
  pinned schedule and complete normalized usage before releasing a hold.
- One-use exchange or refresh may commit before its response is lost. Do not
  persist plaintext for replay or revive the old token. Use existing trusted
  enrollment/successor semantics; never extend the original hard expiry.
  Token refresh, source rotation and policy edits retain old liabilities and
  never replay an invocation.
- Retry HMACs and key versions remain restricted accounting metadata, not logs,
  audit fields or metric labels. Completed duplicates return completion metadata
  without response replay. Preserve bounded previous-key lookup/retention.

## Observed gaps and qualification traps

These are inspection findings against this baseline; the synthetic probe below
does not establish a live-cloud result.

1. **Backpressure can postpone the transport fence.**
   `BrokerInvocation.run()` awaits `_interrupted()` before `_finalize()` cancels
   the provider task. That error write is outside the request timeout and can
   block on the same slow client. Cancellation and upstream closure must not
   depend on downstream error delivery. Bound all sends and cleanup, keep the
   watchdog independent of flow control, and distinguish a JSON response from
   SSE: never append an SSE error to started JSON or start a second response.
   Measure the at-most-five-second check interval, two-second control timeout
   and ten-second fence target under stalls, disconnect, revoke and shutdown.
   A local in-memory probe with a stalled ASGI body send and a rejecting
   continuation call left the provider context open 10.1 seconds after denial;
   external task cancellation then closed it. No provider/network call was made.
2. **Connection limits are not credential abuse limits.**
   Exchange/refresh have no visible per-peer/per-grant throttle in the listeners.
   `http.headers()` bounds each value but has no aggregate byte/header-count
   budget; access bodies are initially read with the larger Messages bound.
   Specify route-specific parsing and pre/post-authentication admission budgets.
   Reuse `shared/rate_limit.py` and `shared/credential_delivery.py` semantics on
   the Engine side where appropriate, with bounded key cardinality and explicit
   failure behavior. Those Django/Redis helpers cannot be imported into the
   broker; local concurrency cannot pretend to enforce a deployment-wide cap.
3. **Async timeout is not cancellation of synchronous work.**
   Control uses `asyncio.to_thread` for identity and `sync_to_async` for Engine.
   A disconnected caller can leave verification, cloud I/O or a database
   transaction running. Bound underlying I/O, database waits and admitted worker
   backlog; keep reserve/dispatch/settle idempotency and ambiguous-result recovery.
   Continuation service capacity must remain available under exchange/source
   request load. Do not retry a provider effect to recover a missing reply.
4. **Identity claim vocabulary needs to be exact.**
   `verify_google_control_assertion` currently compares verified `email` to
   `expected_subject`; it does not explicitly bind `sub`. Resolve this against
   the issue's exact-subject requirement in the existing identity/config seam,
   including account replacement, missing claims, issuer/audience/expiry and
   broker-versus-provisioner tests. AWS's incumbent is a fixed signed regional
   STS assertion with an audience and returned role check, not a JWT parser.
5. **Safe envelopes do not make startup/logging safe.**
   Broker startup directly validates inventory and retained keys; an uncaught
   validation error can include rejected input. `SourceExecutionProjection`'s
   hidden repr does not protect serialization or validation diagnostics.
   `config.logging.ECSFormatter` imports Django and emits exception traces;
   do not import it into the broker or assume it redacts content. Retain the
   existing ECS field convention through a dependency-safe formatting seam if
   broker logging is needed, with explicit service identity and authored fields.
   Audit remains Engine-owned. Bound metric dimensions and scan startup, SDK,
   ASGI/server, error, trace and termination surfaces with synthetic sentinels.
6. **Health and drain are not proved by a successful response.**
   Broker readiness currently reports only `not draining`; `draining` is set
   during lifespan shutdown, while Helm's preStop sleeps. Verify when admission
   actually stops and how active requests close before dependencies disappear.
   Readiness must not claim usable authority from this flag alone. Existing
   listener tests mostly replace transport with ASGI/control/provider ports;
   they cannot establish real TLS framing, socket backpressure, LB/CNI peer
   preservation, rollout behavior or the revocation timing target.

## Extensibility, non-goals and evidence

The extension seam is the existing provider registry plus closed `ProviderTarget`
and capability/billing contracts. Provider/authentication/region/count geography
are independent of compute hosting. Preserve tenant v4 projections alongside
the deployment's stricter workload-identity inventory; do not select inference
providers solely from `CLOUD_PROVIDER`. A new provider/version/billable feature
requires an explicit reviewed adapter and bound/usage semantics, not an arbitrary
URL, import path or tenant executable. Keep shared byte, deadline, protocol and
credential limits in their owning contracts; deployment knobs may tighten the
qualified envelope, never bypass it. Do not add another configuration registry.

M05 does not redesign capacity planning (CTF-908/PLAT-201), source UI/sharing,
allocation, guest bootstrap, direct-access posture or the platform cloud factory.
It does not add server-side tool execution, arbitrary MCP, response storage,
prompt capture (PLAT-215), transparent retries, queues, provider fallback or
cross-cloud qualification. Preserve source revision fences, weights, funding
authority, immutable prices and outstanding accounting already implemented.

Reuse `tests/shared/model_access/test_messages.py`, `test_control_identity.py`,
`test_broker_listener.py`, `test_broker_providers.py`, `test_broker_tunnel_tls.py`,
`test_private_listeners.py`, Engine's `test_model_control_api.py`, credential and
accounting suites, installer/runtime and chart tests. PostgreSQL-marked races
must run against PostgreSQL in the existing `_quality.yml` lane; SQLite cannot
prove exchange/refresh or revoke/dispatch serialization. M05 acceptance also
needs actual local HTTP/TLS with a controllable external provider and slow
clients, including malformed/auth-conflicting traffic and sentinel scans.
Synthetic transport tests and cloud qualification records remain separate.

Required repository checks include
`python3 scripts/adr_guard/adr_guard.py --all --level ci`,
platform Ruff/import-linter for affected Python, and the incumbent
Terraform, Helm/Kubernetes and actionlint checks for affected deployment files.
Honor `.ground-control.yaml`, `docs/adr/index.yaml`, documented exceptions and
the existing quality ownership lanes. No guard relaxation, new workflow service
or claim of PLAT-202 completion follows from this preflight.

Preflight verification: ADR guard at CI level, all nine import-linter contracts,
local documentation links and diff whitespace checks passed. No implementation
or deployment was changed; PostgreSQL races and live qualification were not run.
