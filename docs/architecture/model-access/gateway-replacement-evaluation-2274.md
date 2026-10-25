# Model gateway replacement evaluation — #2274

Evaluated 2026-10-12; selected by the maintainer on 2026-10-13. Status: selected
OSS replacement for qualification; no product has been installed or qualified
by this evaluation.

**Select a separately deployed, self-hosted LiteLLM OSS proxy, with credential
rotation owned by deployment automation.** Bifrost was the second candidate,
particularly if a commercial clustering license is acceptable. Agent Router,
formerly Envoy AI Gateway, fits an organization already adopting Envoy Gateway, but adds more
infrastructure and policy assembly here. Use the product's native transport,
keys and optional controls. Do not build another model gateway in Shifter.

## Decision basis and scope

The maintainer directed replacement and evaluation of existing options on
2026-10-12; the [issue clarification](https://github.com/Brad-Edwards/shifter/issues/2274#issuecomment-6131352734)
records that direction. It supersedes the issue's conditional deferral and
broker-improvement outcome. [ADR-068](../../adr/068-model-access-broker-parked.md)
governs the operating intent: transparent proxying, optional controls with none
enabled by default, automatic credential renewal and integrated bootstrap.
Same-project Vertex sourcing, server-held credentials on the future proxy path,
and administrator-fixed provider routing remain requirements. Configured spend
limits must work; a missing limit means no limit.

On 2026-10-13 the maintainer selected LiteLLM and confirmed that rotation is
automated by the deployment. Use documented OSS key creation/deletion and the
existing Shifter lifecycle and secret-delivery mechanisms. Paid native rotation
is not a prerequisite, and no Enterprise purchase is part of this selection.

ADR-068 records three concrete operating failures: certificates without renewal,
trust creation before the cluster exists on first deployment, and mandatory
finite limits on every request. It also records that live tenants stopped using
the broker. These recorded failures justify evaluating its replacement; they
are not a new deployment reproduction or a benchmark. Current range counts,
arrival rates, concurrent streams and availability targets were not supplied.
Product documentation and repository inspection establish fit, not live support
or measured capacity. Rebuilding the broker would keep its provider translation,
credential and accounting maintenance burden, and ADR-068 rejects that work.

The current supported path remains [ADR-064 keyless-direct](../../adr/064-default-range-model-access.md).
Proxy adoption and the eventual guest-path switch need a separate reviewed
decision. No new hosting, prompt transfer, purchase, provider trial or runtime
change is part of this evaluation.

## Shortlist

The comparisons below describe documented upstream capabilities. Statements
about implementation effort and ranking are engineering judgments for Shifter.
Every candidate still needs the qualification cases below.

| Criterion | LiteLLM | Bifrost | Agent Router |
| --- | --- | --- | --- |
| Client/protocol fit | Anthropic Messages and streaming, Responses and Chat Completions; explicit Claude Code setup. Strongest documented fit for the existing coding-client path. | Anthropic/OpenAI SDK-compatible HTTP interfaces and Vertex transport; exact client features need testing. | OpenAI-compatible and native Anthropic Vertex routes; requires Gateway API routing and processor configuration. |
| Vertex and credential custody | Configured project/region and ADC; provider authentication stays in the proxy. | Configured project/region, ADC including GKE Workload Identity, and OAuth token refresh. | Backend security policy supports ADC/Workload Identity and cross-cloud federation. |
| Optional controls and billing | Native scoped virtual keys, key/team budgets, RPM/TPM and parallel-request limits. PostgreSQL is required for keys and budgets; Redis supports shared enforcement. | Native virtual keys, optional hierarchical budgets and rate controls. OSS state is held in one node; synchronized multi-node governance is Enterprise. | Token quotas and usage-based rate limits through policies, Redis and rate-limit services; monetary billing reconciliation and range-key lifecycle require additional integration. |
| Fixed routing | Static model aliases can select one approved target. Disable retries, fallbacks and caller overrides explicitly. | Provider/model filters and aliases can restrict targets. Disable fallback and unapproved request routing explicitly. | Routes/backend policies select targets. Do not configure provider fallback or trust caller-supplied tenant descriptors. |
| Deployment burden | Separate Python proxy, private endpoint, PostgreSQL and Redis for multiple replicas; documented operating guidance. | Separate Go gateway; attractive for one-node deployment. Supported synchronized HA adds Enterprise procurement and cluster operation. | Envoy Gateway, AI controller/external processor, CRDs/data plane, plus optional quota infrastructure. Largest change to the current stack. |
| License and selection | MIT outside the separately licensed Enterprise directory. Selected OSS edition with deployment-owned rotation; native rotation and JWT/large SSO remain Enterprise features. | Apache-2.0 core; clustering and other Enterprise functions have a separate commercial boundary. Alternative considered. | Apache-2.0; maintainers have renamed Envoy AI Gateway to Agent Router. Prefer if Envoy Gateway is independently selected. |

Protocol sources: [LiteLLM Messages](https://docs.litellm.ai/docs/anthropic_unified),
[client setup](https://docs.litellm.ai/docs/proxy/client_setup/overview),
[Bifrost Anthropic integration](https://docs.getbifrost.ai/integrations/anthropic-sdk/overview),
and [Agent Router Vertex routes](https://theagentrouter.ai/docs/getting-started/connect-providers/gcp-vertexai/).
Identity sources: [LiteLLM Vertex](https://docs.litellm.ai/docs/providers/vertex),
[Vertex partner models](https://docs.litellm.ai/docs/providers/vertex_partner),
and [Bifrost Vertex](https://docs.getbifrost.ai/providers/supported-providers/vertex).
Control sources: [LiteLLM budgets](https://docs.litellm.ai/docs/proxy/users),
[Bifrost budgets](https://docs.getbifrost.ai/features/governance/budget-and-limits),
[Bifrost virtual keys](https://docs.getbifrost.ai/features/governance/virtual-keys),
and [Agent Router quota policy](https://theagentrouter.ai/docs/capabilities/traffic/quota-policy/).
License/maintenance sources: [LiteLLM license](https://github.com/BerriAI/litellm/blob/main/LICENSE),
[Bifrost repository](https://github.com/maximhq/bifrost), and
[Agent Router repository](https://github.com/theagentrouter/agent-router).

### Material distinctions

LiteLLM documents [key creation and management](https://docs.litellm.ai/docs/proxy/virtual_keys)
with PostgreSQL, but marks native key rotation as Enterprise. Its
[client setup](https://docs.litellm.ai/docs/proxy/client_setup/overview) also marks
JWT authentication as Enterprise and sets an edition boundary for SSO scale.
The selected OSS approach issues scoped, expiring keys for range lifetimes and
automates replacement where a workload lasts beyond the permitted credential
lifetime. Orchestration uses key create/delete APIs and the existing lifecycle,
workers and approved secret stores. It does not call licensed regeneration APIs,
enable paid features or introduce another token/exchange protocol. Native
secret-manager integrations are also [Enterprise features](https://docs.litellm.ai/docs/secret);
the OSS integration uses Shifter's existing secret-delivery boundary instead.
Automatic delivery, revocation and accounting continuity must be qualified.

Bifrost's [budget documentation](https://docs.getbifrost.ai/features/governance/budget-and-limits)
explicitly says multiple OSS nodes with PostgreSQL are unsupported because
critical state is retained in memory. Its [clustering](https://docs.getbifrost.ai/enterprise/clustering)
is Enterprise. Shared storage alone therefore does not establish consistent
revocation or budgets across replicas. Its
[virtual-key documentation](https://docs.getbifrost.ai/features/governance/virtual-keys)
also allows requests without governance by default; require inference
authentication independently of whether spend/rate controls are attached.

Agent Router's [quota policy](https://theagentrouter.ai/docs/capabilities/traffic/quota-policy/)
charges token costs after completed requests. Its quota service and Redis are
additional deployments, and enforcement defaults to fail-open if that service
is unavailable. This is useful native quota functionality, but does not prove
pre-dispatch monetary ceilings or accounting parity with the retired broker.
Its [current project](https://github.com/theagentrouter/agent-router) retains the
Envoy AI Gateway deployment names and API group after the rename. Do not select
it only because Shifter already uses Kubernetes.

LiteLLM's [budget documentation](https://docs.litellm.ai/docs/proxy/users) describes
pre-request cost reservation and a fail-closed budget option for degraded
Redis/database state. It also says budgets do not enforce on a DB-less proxy,
and batch jobs cannot be fully priced on submission. These are qualification
constraints, not a promise of exact invoice ceilings. Keep optional financial
controls on the qualified text/streaming endpoints initially; provider bills,
cache pricing, disconnects and concurrent requests must be reconciled.

## Security, privacy and maintenance

LiteLLM's [maintainer incident report](https://github.com/BerriAI/litellm-docs/blob/main/blog/security_update_march_2026/index.md)
records compromised PyPI releases 1.82.7 and 1.82.8 on 2026-03-24. It states that
official proxy-image users were unaffected and describes a revised publishing
pipeline and image signing. Its [security advisories](https://github.com/BerriAI/litellm/security)
include recent authentication, credential-custody and caller-routing defects.
This is a material dependency risk: select a patched, reviewed release, verify
its upstream image signature against a pinned trusted key, retain its digest
and SBOM, and repeat client/security qualification on upgrades. Do not install
an unpinned SDK into Shifter or treat signing as proof that application code is
safe. This evaluation did not install the affected packages or investigate any
Shifter exposure.

Maintenance snapshots are [LiteLLM v1.105.0](https://github.com/BerriAI/litellm/releases/tag/v1.105.0)
(2026-10-11), [Bifrost's release stream](https://github.com/maximhq/bifrost/releases)
(HTTP transport v2.2.6 observed), and
[Agent Router's maintained repository](https://github.com/theagentrouter/agent-router).
These identify active upstreams; they are not deployment pins or security
approvals. A selected immutable release must be checked against then-current
advisories and its actual license/package contents.

For all candidates, expose only qualified inference routes to ranges. Keep
management, model registration, key administration, docs/UI and privileged MCP
off that listener. Require scoped caller authentication even with no optional
controls. Explicit target allowlists, keyless least-privilege IAM and network
egress restrictions must agree. Disable arbitrary provider URL/credential
overrides, environment proxies, cross-provider fallback and hidden SDK/router
retries; test the actual selected version rather than assuming safe defaults.

Retain body-free metrics and authored error categories. Disable prompt/tool/
response logging, semantic response caching, debug wire output and external
callbacks; exclude sensitive request metadata from spend records. LiteLLM
documents [prompt storage settings](https://docs.litellm.ai/docs/proxy/config_settings),
but a setting alone does not prove that exceptions, callbacks and traces are
safe. Use synthetic sentinels across success and failure paths. Hosted gateways
and telemetry exports are outside the current tenant processing boundary and
need separate authorization; none is used here.

## Smallest proposed LiteLLM integration

1. **One isolated product deployment.** Deploy a pinned official proxy image
   through the existing installer, Helm and GCP bootstrap/deploy flow, with its
   own service account, restricted secret mounts and private inference endpoint.
   Keep it outside portal/provisioner processes and outside the public portal
   listener. Give it a dedicated database/user with no access to Engine tables;
   use a separately isolated Redis service for multiple replicas. Existing
   cloud provisioning patterns may be reused; shared portal database credentials
   or an existing Redis instance's spare capacity are not assumptions.
2. **Vertex first.** Map approved logical aliases to fixed dated publisher
   models, regions and the deployment's existing GCP project. Use gateway-held
   Workload Identity/ADC and exact invocation grants. Other projects/accounts
   remain optional, not a prerequisite. Bedrock/direct providers and additional
   protocols follow only after independent qualification.
3. **Native gateway keys and controls.** Engine retains tenant/source-use and
   range-operation authority. A narrow integration calls native gateway key
   create/revoke operations and delivers only the scoped gateway credential
   through existing operation/secret delivery and the public adapter SDK.
   Bind it to the admitted range generation, allowed aliases and lifetime;
   guests never receive the administrator key or provider credentials. For
   automatic rotation, use the deployment-owned sequence below through documented
   OSS APIs and secure delivery. Do not revive the bespoke enrollment/freshness
   protocol. Attach budgets/RPM/TPM/concurrency/detections only when explicitly
   configured; no finite defaults, zero caps or large-number unlimited sentinels.
4. **One accounting authority per new workload.** Use the selected product's
   native optional usage/budget mechanisms rather than reserve the same request
   in both gateway and old Engine ledgers. Engine keeps source-use authority and
   lifecycle/audit references, not a gateway financial counter. This proposed
   authority change needs an explicit migration decision. Preserve old Engine
   liabilities and immutable history read-only; do not reinterpret v1–v4 finite
   policy fields as unlimited. Any new installation policy needs its own
   versioned contract and owner-service validation.
5. **Standard private TLS renewal.** The existing GKE public managed certificate
   does not prove renewal for a private gateway hostname. Select a standard
   automatically renewing private TLS integration, such as cert-manager with
   an approved issuer, and qualify issuance, trust delivery, renewal and reload.
   cert-manager is a proposed additional dependency, not an installed facility.
   No new CA/issuer service is authorized by this recommendation. Create cluster
   and issuer prerequisites before gateway enablement; no hand-created trust
   objects or near-expiry deploy refusal. Provider token refresh, gateway-key
   rotation and TLS renewal are three distinct responsibilities.

LiteLLM's [production guidance](https://docs.litellm.ai/docs/proxy/prod) recommends
PostgreSQL connection budgeting, Redis for multiple proxy instances, bounded
timeouts and one worker per Kubernetes pod. Its stated starting resource floor
is 1 vCPU/4 GiB per worker; treat that as vendor sizing guidance and validate it
against the actual stream workload. Do not inherit permissive chart autoscaling
or long request timeouts without assessment.

### Deployment-owned rotation

Run rotation in existing lifecycle workers and durable operations. Use a fixed
range generation and stable credential-set identity; keep secret values in the
approved secret store and only references in operation records.

1. Recheck current range/source authority and create an expiring replacement
   gateway key with the same approved models and owner. Keep the original key's
   deadline; replacement must not extend a stopped or reset generation.
2. Publish the replacement through existing secret/operation delivery. The guest
   credential helper must refresh without manual changes, using the public SDK
   boundary. A version-bound acknowledgment confirms installation for the current
   generation, not just that a server-side secret exists.
3. Revoke the old key after acknowledgment, within a bounded overlap window.
   Reconcile failed delivery and missed acknowledgments without extending old
   credentials indefinitely. If refresh fails, the original key expires at its
   deadline; there is no direct-provider fallback. Stop/reset revokes both keys.
4. Resume after worker restarts or lost create/delete replies using durable
   operation state and gateway key identifiers. Find and retire orphaned
   replacements; do not blindly create more keys, refund usage or resurrect a
   revoked key. Recheck generation before every delivery and revoke credentials
   created by a stale operation.

Where spend controls are configured, both keys must share the same persistent
native budget owner and window. Creation of a new key must not create another
spending allowance. For example, a synthetic budget of 100 units with 60 spent
retains 40 units across both keys during overlap and after revocation. Preserve
usage and outstanding charges under their original owners; do not copy a
remaining balance into a fresh per-key counter and then discard the old counter.
With no spend control configured, rotation must not add one. Gateway-key
replacement, provider Workload Identity refresh and TLS renewal remain separate
operations. This section specifies qualification behavior, not implemented
automation or a new credential service.

## Migration cost and delivery boundaries

The first slice is GCP/Vertex, one qualified client and a private endpoint. The
work is integration and operation: installer/schema projection, IAM/network/TLS,
native key creation/revocation, rotation orchestration, guest SDK endpoint
settings and targeted tests. It does not require a generic gateway abstraction,
another provider codec or rewriting
the model-source UI at the same time. Tenant administration remains Shifter's
responsibility; product administration remains private.

Expected operating costs are gateway replicas/resources, isolated PostgreSQL
storage/backups, Redis, TLS renewal and operation of deployment-owned rotation.
No Enterprise license is selected. LiteLLM adds dependency and upgrade
qualification work; Bifrost adds Enterprise cost for supported synchronized HA;
Agent Router adds control-plane
and quota-service operation. No vendor quote, measured traffic or cloud cost
model was supplied, so dollar totals and a migration duration would be invented.

Qualify on an authorized non-production deployment with synthetic traffic,
without shadowing real prompts. Then make a separate reviewed decision to move
guests from keyless-direct to the qualified proxy. For that slice, remove direct
provider authority and egress bypass; a proxy outage cannot trigger direct
fallback. Rollback is an explicit operator transition between qualified modes,
including credential fencing, not request-level failover. Retain legacy usage,
outstanding liabilities and restore evidence. Only after cutover and dependency
inventory should another change remove parked broker code, infrastructure and
UI assumptions. This evaluation neither files implementation issues nor removes
any of those assets.

## Qualification required before adoption

| Case | Required evidence |
| --- | --- |
| Pinned client/protocol | Real Anthropic JSON and SSE, tool use/results, token counting, cache/thinking/beta features actually used, errors and cancellation through the selected Vertex model. Record client, model and image versions; reject unsupported features before billing. Responses/other protocols have separate qualification. |
| Default with no controls | An authenticated permitted request succeeds without spend/rate/concurrency/token policies. Missing limits stay absent across installer, runtime and native keys; caller authorization and transport resource bounds still apply. |
| Configured controls | Native spend/RPM/TPM/concurrency controls deny appropriately under concurrent streams and multiple replicas. Exercise zero vs absent limits, missing prices, DB/Redis loss or stale state, cancellation and ambiguous dispatch. Confirm configured caps do not become fail-open or erase usage on restart. |
| Credential lifecycle | OSS key create/delete, range reset/generation change and stop, startup longer than the old freshness window, expiry and deployment-owned rotation with automatic guest refresh. Exercise lost create/delete replies, orphaned replacements, failed delivery, missed acknowledgments, bounded overlap, stale operations and worker restart. Measure cross-replica revocation delay; old credentials do not resurrect after restore. |
| Rotation accounting | With a configured persistent native budget owner, old and new keys share one remaining allowance during overlap. Rotation, retries and restart retain spend, unresolved charges and the budget window; expiry/deletion cannot reset usage. With no configured controls, rotation adds none. |
| Identity/routing/privacy | Same-project keyless Vertex; denied foreign tenant/model/admin access; fixed provider destinations and identities despite untrusted inputs; no direct bypass or hidden billed replay. Inspect logs/errors/traces/artifacts using synthetic secret and prompt sentinels. |
| Bootstrap and renewal | First enablement on a fresh cluster without manual trust objects; automatic certificate renewal/reload and provider token refresh during active streams; restart and near-expiry redeploy succeed without turning off TLS verification. |
| Operation and recovery | Draining, pod/node loss, upgrades and DB/Redis restore; measure p95/p99 added latency, concurrency, memory and provider errors at the declared workload. Retained liabilities, native state recovery and controlled rollback must work. |

Selection is **self-hosted LiteLLM OSS with deployment-owned rotation**. Private
TLS and runtime qualification remain to be established. If the chosen release
cannot pass the mandatory client, privacy, fixed-routing, renewal or configured-control
cases, do not compensate by rebuilding gateway machinery: reassess Bifrost
(including its Enterprise HA cost) against the same cases. No candidate's
marketing throughput or provider count substitutes for this evidence.
