# Vertex invocation and usage adapter preflight — #2124 / M07

Architecture guidance for PLAT-202, inspected at `26e03790266a` on
2026-09-20. This applies [ADR-059](../../adr/059-range-model-access-broker.md),
[ADR-060](../../adr/060-model-access-allocation-accounting.md) and
[ADR-061](../../adr/061-model-access-operations-qualification.md) to the current
repository. It is not an implementation plan, a provider-support claim or live
qualification evidence.

## Decision and observed gaps

M07 is an adapter and compatibility-qualification change inside the existing
broker boundary. It does not create another gateway, provider catalog, ledger,
credential service or guest lifecycle. The participant contract remains the
qualified Anthropic Messages subset; the provider contract is fixed Vertex
publisher-model REST. Engine remains the only accounting and dispatch authority.

The checkout already contains a partial Vertex path in
`model_broker/providers.py`, `provider_credentials.py` and `provider_usage.py`.
Treat it as the incumbent to harden, not as acceptance evidence:

- `MessagesProvider` currently mixes Vertex, Bedrock and direct-provider routing.
  Reuse `ProviderAdapterRegistry`, `ModelProviderAdapter`, `ProviderTarget` and
  the shared billing/usage DTOs. Do not add another registry or deepen a generic
  provider switch with Vertex-only policy. Provider-specific request/response
  codecs may be separated behind the incumbent adapter seam; broker lifecycle,
  Messages validation and accounting stay provider-neutral.
- `BrokerInvocation` reserves a full context-window input bound before
  `MessagesProvider` calls the provider count endpoint. That is safe but does
  not meet M07's routine-small-request acceptance criterion. A qualified smaller
  bound must come from the exact validated request and a provider-proven count
  (or another documented proof). Counting is itself an accounted, authority-
  checked provider operation; it cannot become an unrecorded broker-local
  preflight. Reuse the existing reserve/dispatch/settle lifecycle for the count
  and paid invocation, or extend that lifecycle atomically. Do not create a
  process-local credit, mutate a dispatched hold, estimate from characters or
  reserve the paid call before obtaining the smaller bound.
- `_vertex_headers()` obtains a fresh impersonated credential for every upstream
  operation. M07 requires bounded, early-expiring, in-memory token reuse with
  single-flight refresh, keyed by the complete approved identity/authentication
  target. The cache is an availability optimization only: it never caches grant
  authority, accounting decisions or provider responses; tokens never cross the
  broker process or appear in logs, exceptions, environment, files or metrics.
- Vertex JSON and SSE are bounded, but the existing path mostly relays provider
  objects/events after usage inspection. Extend the canonical closed Messages
  contract in `shared/model_access/messages.py` (and the incumbent provider
  codec) for the observed response surface. Validate event ordering, indices,
  block shapes, terminal state and complete usage before treating a response as
  successful. Never blindly forward unknown provider fields or headers, and do
  not define a second request/response schema beside `shared.model_access`.
- Non-200 responses currently collapse to `provider.unavailable`, while the
  participant listener maps almost every `ContractError` to HTTP 409. Reuse the
  existing `ProviderError` category/retry vocabulary, `NoBillableEffect` proof
  and fixed Messages error envelope. The client-facing status/category matrix
  must be qualified against the pinned client's behavior; provider bodies,
  headers, request IDs and exception strings remain private. A timeout,
  disconnect or ambiguous response after possible dispatch is never
  `NoBillableEffect` and never authorizes replay.
- The shared upstream client currently has a five-second default read timeout.
  That is not qualification of a useful streamed coding response. Preserve the
  absolute request/grant deadline and bounded connect, pool, write, stream-idle,
  event and total-response limits as separate controls; tune them only from the
  observed client/provider path and never disable them to make streaming pass.
- `installation/model_broker_runtime.py` currently restricts the initial mounted
  workload-identity inventory to Vertex on GCP and Bedrock on AWS. Do not remove
  that deployment gate under M07 or consult `MODEL_BROKER_PROVIDER` from the
  adapter. It names the hosting/control-identity cloud, while
  `ProviderTarget.provider` names inference. Platform-project and external GCP
  projects fit M07; cross-host packaging/support needs its owning qualification.
- The guest image scripts currently install an unversioned client and configure
  direct Bedrock. M07 must record one exact released client version and its wire
  corpus/configuration contract. M08 (#2125) owns installing the broker endpoint,
  credential helper and lifecycle-bound capability into guests. M07 must not
  duplicate enrollment to make a test pass, and M08 must consume the same pin
  and settings proven here rather than introduce a second compatibility target.

No new ADR is needed for these constraints: the existing ADRs already decide
provider isolation, pre-dispatch accounting, unknown-outcome retention and
qualification. Change an ADR only if implementation needs to change one of
those decisions.

## Canonical incumbents and concept boundaries

Keep these identities separate in types, configuration and evidence:

| Concept | Canonical owner and required use |
| --- | --- |
| Participant model name | The logical alias in `ModelAccessAuthorization`; the client never chooses a Vertex project, region, publisher path or service account. |
| Physical target | `ProviderTarget.bind()` plus the allocation's immutable shard: exact adapter, project, inference region, count geography, pinned publisher model/version, credential reference and protocol. Build both count and inference URLs only from this target. |
| Hosting/control identity | `MODEL_BROKER_PROVIDER`, `WorkloadIdentity` and control audience authenticate the broker to Engine. They do not select the inference provider or target project. |
| Invocation identity | `ProviderCredentials` impersonates only `ProviderTarget.principal`; Terraform/readback and `model_broker_runtime._validate_execution_inventory` bind it to approved project inventory. Platform-project and external-project targets are both valid. |
| Provider quota | v2/v3/v4 catalog provider-pool membership and Engine `_model_quota` services. Models, aliases or GSAs sharing a real quota pool reference the same pool; identity count never multiplies capacity. |
| Price and liability | The allocation snapshot, `ModelRequestReservation`, postings and `_priced_schedule`. The adapter reports bounded units and verified usage; it neither chooses prices nor computes an authoritative charge. Source/model changes do not rewrite old prices or liabilities. |
| Client compatibility | One pinned client version, fixed installed settings and a sanitized real wire corpus. It is not a provider capability, catalog alias or mutable runtime default. A client upgrade is a new compatibility qualification, not an implicit parser widening. |

`catalog_v3.py` remains the installed accounting authority and `catalog_v4.py`
the allocation-specific source overlay. A target projection cannot override the
allocation's shard, price or authority. Do not conflate source display names,
secret revisions, service accounts, projects, quota pools or financial accounts.

## Cross-cutting passage requirements

Every layer below is cumulative; passing the local provider test is insufficient.
Paths under `shifter/shifter_platform/` are shortened in this table.

| Layer and canonical incumbent | Required passage for M07 |
| --- | --- |
| Participant HTTP and authentication: `model_broker/server.py`, `shared/model_access/http.py`, `credentials.py`, `traffic.py` | Preserve private TLS, actual socket-peer binding, opaque range capability authentication, route/method/content-type restrictions, duplicate/conflicting-header rejection, framing/compression and byte/depth limits. Only logical aliases cross this surface. Unknown client headers are classified from the qualified corpus: security/hop-by-hop fields reject, proven inert client metadata may be ignored, and semantic/billing fields must be explicitly supported or rejected—never wildcard-forwarded. |
| Messages shape and protocol: `shared/model_access/messages.py`, `model_broker/providers.py`, `provider_usage.py` | Reuse closed Pydantic models and `strict_json` duplicate-key/depth/non-finite checks. Pin `anthropic-version`; admit beta/body features only when the observed client path, Vertex behavior, billing bound and usage settlement are all qualified. Preserve supported local tool use/results as data. Unsupported cache, thinking, media, server tools, citations or other cost-changing features fail before billable transport unless the pinned central client setting demonstrably omits them. |
| Control wire and online authority: `model_broker/control.py`, `shared/model_access/control_wire.py`, `engine/model_access_control/{schemas,server}.py` | Reuse closed request/reply DTOs, workload-authenticated private TLS and two-second bounded calls. Count and invoke each require current grant/peer/epoch authority immediately before their own transport. A malformed or missing control reply fails closed; no offline/cached authorization is introduced. Prompts and provider tokens never enter Engine control requests. |
| Accounting and persistence: `engine/services/_model_request_{accounting,lifecycle,reconcile}.py`, `_model_quota.py`, `engine/models/_model_budget.py` | Use the existing PostgreSQL lock order, immutable allocation/price/account snapshots, distinct postings, one-shot dispatch leases, strict pre-dispatch audit and retained unknown obligations. A provider-proven count may narrow only the exact immutable request's input units; output and every enabled billing component retain hard maxima. No provider I/O under database locks and no cache/Redis/process counter as financial authority. |
| Target/config validation: `shared/model_access/{provider,provider_runtime,catalog_v2,catalog_v3,catalog_v4}.py`, `installation/{loader,model_access,model_broker_runtime,gcp_model_broker}.py` | Evolve closed consumers together. Preserve schema/digest validation, target-to-shard binding, enabled-v3 pricing checks, exact applied-identity readback, 96 KiB mounted-config budget and disabled defaults. Project, region, count geography, publisher model/version and principal are server-owned and explicit; there is no `global`, `latest`, arbitrary base URL or participant override. |
| Credential and secret handling: `model_broker/provider_credentials.py`, `shared/model_access/source_credentials.py`, `SourceExecutionProjection`, cloud-owned secret adapters | The first qualified Vertex path is keyless workload impersonation to the exact target. Stored source credentials remain a distinct, revision-bound mechanism and are not a fallback. Bound metadata/IAM calls and concurrency; cache only short-lived access tokens in broker memory with early expiry. Never expose a token or service-account key to guests, control payload logs, tracebacks, crash reports or support evidence. |
| Provider transport and network: the broker `httpx.AsyncClient`, `egress.py`, `egress_proxy.py`, chart `model-broker-network.yaml` and `model-provider-egress.yaml` | Construct only approved regional Vertex count/raw-predict/stream-raw-predict routes, use verified TLS/hostname checks, `trust_env=False`, explicit CONNECT proxy, pinned public resolution and the workload-identity metadata exception. Keep redirects, provider retries, fallback and caller-controlled destinations disabled. Assess the union of NetworkPolicies; the proxy has no identity and the broker gains no arbitrary internet/private-control reach. |
| Process/OS exposure: `model_broker/__main__.py`, `installation.gcp_model_broker.BROKER_RUNTIME_ENV_KEYS`, chart `model-broker.yaml`, container security context | Continue bypassing application secret hydration and Django settings. Environment/argv/ConfigMaps contain only fixed paths, origins, non-secret IDs and digests. TLS/HMAC material stays in read-only mounts; provider tokens stay memory-only. Do not add tokens to shell interpolation, process arguments, Terraform state, operation JSON, image layers or temporary evidence files. |
| Errors, audit and observability: `ProviderError`, `ContractError`, `NoBillableEffect`, broker `_error`, `shared/model_access/diagnostics.py`, `shared.audit` | Normalize to bounded authored categories/codes and the fixed Messages JSON/SSE envelope. Suppress dependency wire logging even under DEBUG. Engine audit/accounting records safe correlation and decisions before dispatch; prompts, responses, tools, tokens, raw provider diagnostics and high-cardinality user/range labels remain forbidden. Provider rate-limit metadata may influence an authored bounded delay but is never reflected wholesale. |
| Dependency and image provenance: `shifter_platform/pyproject.toml`, `uv.lock`, `requirements-gcp.{txt,lock}`, Packer scripts/workflows and image evidence | Direct REST remains the transport; do not add a Vertex generative SDK. Pin and attest the client plus actual `httpx`, `google-auth` and transitive transport/auth versions used by the broker image. One production pin feeds every qualified guest variant; unversioned `npm install` or a fixture claiming a different version is not acceptance. |

The relevant whole-repository deployment consumers are the GCP model-broker
Terraform/IAM modules, `platform/deploy/gcp/*/model-broker-overlay*.json`, Helm
broker/control/network/egress templates and schema, `scripts/gcp/` render/probe/
image-verification tools, `scripts/check_tf_gcp_iam_resource_scope`, Packer image
scripts and validation workflows, and `.github/workflows/` quality/deploy lanes.
M07 need not edit all of them, but no changed target, dependency, environment or
client setting may bypass their closed shapes and provenance checks.

## Vertex protocol, accounting and failure guardrails

- Count and paid invocation use the same already-validated immutable Messages
  value. The count must cover system content, message blocks, tool schemas and
  every admitted feature. Reject counts beyond request, grant or physical
  context limits. A count failure proves only that no paid invocation followed;
  it does not prove the count transport had no effect unless its qualified price
  and provider semantics say so.
- Reserve input using the proven count, output using the accepted `max_tokens`,
  and any other admitted component using its proven maximum. Engine applies the
  immutable shard-specific price schedule and all distinct spend/rate/
  concurrency accounts. Missing price, usage field or count/price validity
  fails closed. Cache discounts are not assumed; cache writes or other default
  features are rejected unless their complete upper-bound and settlement
  semantics are added to the existing contracts.
- JSON and SSE success require a complete provider response and complete
  provider-verified usage. Enforce total response/event/buffer/deadline bounds,
  event ordering and terminal completion. Truncation, malformed events,
  disconnect, cancellation, timeout or absent usage leaves the paid request
  unknown and retains its conservative hold. Closing HTTP transport does not
  prove Vertex execution stopped.
- Provider 4xx/429/5xx responses are classified without parsing or returning
  unbounded diagnostics. The broker performs no provider retry. Whether the
  pinned client retries each normalized status must be observed; ambiguous
  dispatch must not be turned into a second billable request. Existing scoped
  idempotency/HMAC handling remains the only deduplication mechanism and never
  stores response bodies.
- Main and small aliases, each configured project and every target model version
  are independent positive cases. Routing remains the allocation's exact alias
  map; there is no failover between projects/models, no mid-stream reassignment
  and no fallback to a direct guest identity. Shared quota-pool references—not
  service-account or alias names—serialize real provider capacity.

## Extension seam and evidence boundary

The required extensibility seam is the existing closed provider target plus
provider adapter/capability registry. The parameter is an immutable target
revision containing provider adapter ID, project/account, inference region,
count geography, pinned provider model/version, authentication/credential
reference, protocol/features, context bound and real quota-pool identity through
the catalog. Adding another approved Vertex project or model is data plus
qualification; it must not require a new URL branch, IAM role shape, scenario
field or accounting implementation. Adding a new client/protocol version is a
new closed codec/capability revision and wire corpus; it does not loosen the old
parser in place.

Qualification must use sanitized requests captured from the exact pinned client
and installed-settings contract, not hand-authored approximations. Cover startup,
model listing if used, count, non-stream JSON, SSE, useful multi-turn local-tool
use/results, both aliases/projects, default headers/body features, budget edges,
provider errors, malformed/truncated usage, slow/disconnected clients and
unsupported-feature rejection. Synthetic fixtures belong in the owning broker
tests and must carry the client/config version metadata that produced them.
They contain synthetic content and no authorization/provider tokens.

Run one separately budgeted live positive call for every enabled project/alias
before activation and record project/model/region, client/dependency/image
digests, price/quota/retention prerequisites and safe outcome metadata in the
protected evidence surface. Do not commit prompts, provider diagnostics,
credentials or private operational identifiers. Local mocks, rendered manifests
and a successful count are not live invocation or deployed IAM/network proof;
M10 (#2127) owns independent deployed boundary evidence.

## Non-goals and anti-patterns

M07 does not implement guest enrollment/refresh or image delivery (#2125),
tenant source UI/public APIs (#2243), deployed IAM/network/revocation proof
(#2127), Bedrock/direct-provider parity, external tools, PLAT-215 prompt capture,
capacity-planner redesign or a new provider SDK. It does not change RAES, create
per-range model projects, execute tool calls, store responses, add a retry queue
or make direct access an outage fallback.

Avoid arbitrary provider URLs; mutable model aliases; `latest`/global routing;
prices in adapter code; quota inferred from GSAs; provider tokens in env/argv;
generic exception strings; raw SDK/debug logging; hand-maintained duplicate
Messages schemas; silent beta/field stripping; full-context reservations claimed
as small-request support; broker-local financial counters; automatic retries,
redirects or fallback; and tests that mock the adapter method instead of proving
real HTTP serialization, TLS/error framing and accounting behavior.
