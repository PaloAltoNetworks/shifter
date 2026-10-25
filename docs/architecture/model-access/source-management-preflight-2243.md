# Tenant model-source configuration preflight — #2243

Architecture guidance for PLAT-202, 2026-09-18; inspected baseline `b44273f98`.
This records boundaries and acceptance risks, not an implementation plan or a
claim of installed provider support. ADR-059 through ADR-061 remain authoritative.
#2243 expands tenant management and provider choice; removing a deployment check
does not satisfy it or close the broader PLAT-202 tracker.

Paths below omit `shifter/shifter_platform/` for platform modules and `shifter/`
for `installation/`. Other paths are repository-relative.

## Decision and current gaps

A **source** is an authorized tenant configuration of provider invocation and
broker-held identity. It is not a compute backend, logical model alias, scenario
adapter, quota pool, financial account or participant credential. Build its
management surface on Engine's existing catalog/publication authority and
`shared.model_access`. Source metadata/revisions belong to Engine; organization,
workspace and event authority remain with their owning services. A source can
supply several model/region shards. Rotating a credential need not change its
real provider quota identity, budget account or selected model.

The existing allocation, sharing, accounting, control and enrollment seams cover
much of this requirement. These gaps materially constrain the extension:

| Observed incumbent | Consequence for #2243 |
| --- | --- |
| `config/_model_access_settings.py` loads a process-start mounted catalog; sharing publication pins its digest. | UI writes alone cannot activate a source. Engine needs revision-fenced publication consumed consistently by admission and broker routing. Files, process globals and UI tables cannot become competing live authorities. |
| `shared/model_access/provider_runtime.py:ProviderTarget` accepts Vertex/Bedrock and binds Anthropic Messages; `model_broker/providers.py` implements that subset. | OpenAI, direct Anthropic, OpenRouter and conforming integrations need explicit transport, credential, capability and billing contracts. A select option or arbitrary provider string is insufficient. |
| `installation/model_broker_runtime.py:_validate_execution_inventory` requires Vertex on GCP and Bedrock on AWS. | Separate hosting/control identity from inference identity. Cross-cloud sources need working bounded credential acquisition and approved egress, not a bypass of this validator. |
| GCP model-broker IAM maps one invocation account per selected project and permits the platform/dynamic-secret project as a source. | Retain distinct broker/invocation identities and exact-target IAM when projects coincide; project inequality and one-project/one-source assumptions are invalid requirements. |
| `engine/services/_model_allocation.py:_replay` keys allocation by request, operation and workload role and rejects changed intent. | Live editing is an explicit policy transition, not allocation replay or an in-place shard rewrite. Do not invent another range execution generation to bypass uniqueness. |
| `shared.cloud.types.SecretsStore` only retrieves; its AWS adapter imports Django settings and logs provider exceptions. | Secret administration needs bounded write/version/retire semantics at the incumbent storage boundary. The broker cannot import that adapter unchanged or assume retrieval supplies write-only administration. |

## Authority, publication and user intent

Organization administrators may manage sources within their tenant and the
deployment's approved transport, IAM, data-policy and spending envelope. Reuse
`workspaces.services.resolve_administrable_organization` and locked authority
patterns, including audited platform overrides; staff status alone is not
tenant authority. Registration does not grant everyone permission to spend the
source's funds. Source-use eligibility participates in existing owner/sharing
projections and fences, not a parallel ACL evaluator in the broker or UI.

Source administration, source use, scenario authoring, event organization and
editing another user's range are distinct permissions. Resolve standalone
launch authority through CMS/workspace services and CTF authority through
`ctf.services`/organizer capabilities. CTF participation does not confer ordinary
workspace or source-administration privileges. Scope list, detail, preview,
validation, rotation and mutation consistently: guessed source, credential,
pool, event or range IDs must neither disclose nor authorize foreign resources.
Reauthorize under the owning transaction after external I/O.

Scenario needs remain logical, package-digest/workload-role-bound CMS projections
(`cms/scenarios/model_needs.py`) until RAES supplies a matching released contract.
Selections reference approved sources/aliases and restrict those needs; they
cannot put provider coordinates or secrets into packs. Event defaults and
per-alias/participant/pool choices enter existing effective-policy intersection
and explicit overlap-priority rules. Overrides outside delegated authority
reject rather than silently widening or clipping access. Defaults must be
visible, compatible and authorized; required access fails closed and optional
absence is explicit. Changing a default cannot silently reroute live ranges.

Engine publication is the single live authority. Reuse `_sharing.py` immutable
revision/CAS conventions, catalog validation/digests and owner projections bound
in `config/model_access_sharing.py` and `config/model_access_authority.py`.
Deployment imports and UI writes use the same publication semantics. Keep
installation-owned transport/IAM maxima separate from tenant policy; deployment
reapply must not overwrite tenant choices or resurrect revoked sources. Existing
revisions/allocations retain original catalog, source, credential-version,
price, account and cleanup references.

A revision is usable only when the broker can resolve its exact approved
target/credential projection and Engine can admit it. Stale/missing projections,
partial publication and old replicas fail closed. Broker execution projections are ephemeral, secret-bearing, bounded and
authenticated through existing workload/control seams;
the broker never reads Engine tables. Ordinary selection among prepared sources
requires no deployment-file edits or infrastructure apply. Initial broker,
egress/IAM setup and onboarding an unprepared external identity are separate
prerequisites, surfaced as unavailable with a bounded reason, not fabricated
success or an automatic broad-IAM grant.

## Changes, allocation and retained liability

Source, credential, event-policy and range-policy mutations compare expected
revisions and reauthorize; previews are advisory. An accepted range change
fences old grants/dispatch leases before new use, then requires fresh admission
and enrollment through the incumbent lifecycle. Never mutate an allocation
snapshot, reset spent counters or overwrite cleanup references. Failed
replacement stays visibly unavailable/revoking; it cannot restore the old epoch.
Policy-edit identity must fit existing operation and grant/revision contracts so
replay, recovery, resume and stale cleanup remain unambiguous. Reusing the launch
idempotency tuple with changed intent is a conflict, not a range-edit mechanism.

Reuse `_model_allocation_authority`, `_model_allocation_lifecycle`,
`_model_request_accounting`, `_model_request_lifecycle` and
`_model_request_reconcile`. Retain canonical lock ordering, conditional writes,
PostgreSQL uniqueness/check constraints and strict transactional audit. Do not
hold database locks across provider/secret-store calls. External writes need
idempotent version identities and bounded compensation through existing
service/reconciliation conventions. Failed publication cannot leave a usable
unowned secret; retirement cannot destroy externally owned credentials or
evidence needed by unresolved requests.

Existing dispatches settle against original sources, immutable prices and
deduplicated accounts. Unknown outcomes retain conservative liability; editing,
disabling or rotating a source is neither a refund nor permission to replay.
Admission fencing and transport revocation are separate observable states;
provider execution may remain billable after delivery stops. Preserve ADR-061's
revocation target across replicas. Authority loss, compromise and source disable
must fence dependent active grants synchronously, not only during a refresh job.

Reuse `allocation.py` weighted-rendezvous vectors, provider-pool membership,
per-alias affinity and `_model_quota` real-quota locking. Weights express intended
distribution, not extra quota or exact participant counts. Capacity eligibility
uses fresh observations and durable reservations. CTF-908 roster/spare demand
and PLAT-201 assessment remain inputs; CTF's best-effort capacity exception
handling is not a required-model admission gate. Cold launches, spares, warm
claims, recovery and resume stay on CMS's incumbent admission/allocation paths.
Shared spend/rate/concurrency and optional per-range limits are independent
facets, applied once per distinct account; source switching cannot evade
deployment/event/user lifetime caps.

## Cross-cutting passage requirements

These gates are cumulative. Passing a local validator does not establish the
whole boundary.

| Layer and canonical incumbents | Required passage |
| --- | --- |
| UI: `frontend/src/api/{client,csrf,queryClient,errors}.ts`, generated `schema.d.ts`, existing organization/scenario/CTF/range surfaces | Same-origin session/CSRF and safe errors; no second fetch/retry framework. Mutations do not auto-retry; tenant/resource-scoped caches invalidate after edits and 409 is explicit. Credentials stay transient in write forms, never URLs, storage, query/mutation persistence, read DTOs or diagnostics; clear after submission/unmount. Show effective defaults, affected ranges, pooled/individual limits and unavailable reasons. |
| Public API: `shared/api/{permissions,principals,contract}.py`, `shared/api_tokens/{authentication,permissions,scopes}.py`; tenant precedent `cms/api/runtime_plugins.py` | Session-only tenant administration (`IsAuthenticatedSession`) is an existing pattern. If tokens are admitted, require registered scopes **and** active actor/domain authority. Bad bearer credentials cannot fall through to sessions. Preserve object authorization, OpenAPI/contract inventory and bounded pagination. Read DTOs expose safe metadata/credential-present status only. |
| Input/schema: `core_models.ClosedModel`, `catalog.py`, `digest.py`, `messages.strict_json`, `installation/{loader,model_access}.py` | Bound raw input; reject duplicate members before decoding loses evidence, unknown keys, coercions and inconsistent references. Apply canonical semantic/digest validation. Default DRF JSON decoding/ignored fields are insufficient: reuse strict parsing and the closed-serializer convention in `cms/api/preparation_adapters.py`. Do not duplicate policy validation in forms. Generate versioned installation schemas from shared models with parity/golden vectors; do not reinterpret stored v1/v2/v3 meanings. |
| Secrets: `ProviderCredentialReference`, `model_broker/provider_credentials.py`, `shared.cloud.types.SecretsStore`, cloud adapters; write-only precedent `cms/api/runtime_plugins.py` | Separate metadata, reference and bytes. Validate store/tenant/owner/version server-side; a submitted ARN/path is not permission to read any broker-accessible secret. Prefer short-lived workload identity where available. Registration/rotation is write-only over TLS; only the authorized broker resolver retrieves invocation material at runtime. Bound acquisition timeouts/retries, version/invalidate caches and reject plaintext/ciphertext readback or provider diagnostics. |
| Storage: incumbent secret adapters; `shared/field_encryption.py` where application-held sensitive fields are necessary | Define writer/read permissions, ownership, rotation and cleanup; secret-store writes and DB publication are not atomic. Reuse encryption primitives, but transparent ORM decryption is not broker isolation. CMS guest credential hydration and `engine/secrets.py` caches are not provider delivery. Never give the broker Django settings, database access or the platform field-encryption key to enable reuse. |
| Persistence: Engine services/models, `effective_policy.py`, `authority{,_port}.py`, owner projections and shared audit | Tenant-bound immutable revisions, CAS, transactional source-use authority/grant fences, finite integer money and retained ledgers. No process-local live catalog authority, browser-calculated budgets, Redis-only ledger or cascading deletion of accounting history. |
| Installation/runtime: `installation/{loader,model_access,model_broker_runtime,gcp_model_broker,aws_model_broker}.py`, `config/_model_access_settings.py`, `shared/model_access/runtime.py`, `model_broker/__main__.py` | Evolve every closed consumer of source/auth shapes together. Reuse schema/semantic validation, path/digest checks, exact inventory and disabled defaults. Keep routing and policy revisions consistent; a DB edit cannot bypass mounted/startup contracts. Respect distinct runtime and Kubernetes transport size limits. |
| Environment/host: `BROKER_RUNTIME_ENV_KEYS`, installation deployment inventories, `scripts/gcp/{render_runtime_env,render_model_broker}.py`, `scripts/bootstrap/aws_eks.py`, chart broker/control templates, `shared/cloud/sensitive_env.py` | Configuration carries only non-secret references/paths/digests. No provider keys in argv, shell interpolation, environment literals, manifests, ConfigMaps, Terraform state, subprocess output or CI artifacts. Broker-only restricted secret mounts/resolution; no portal `envFrom`. Env-name classification is defense in depth, not permission to send provider secrets to provisioner Jobs. No shell-based credential onboarding. |
| IAM/network: GCP `portal/iam`, `platform-core`, project services/readback; AWS broker IAM; chart `model-broker-network.yaml`; `scripts/check_tf_gcp_iam_resource_scope`, `scripts/gcp/probe_model_broker.py` | Platform/model project equality is allowed; principals, permissions, quota, compute and dynamic-secret roles stay distinct. Preserve exact invocation/token grants, separate control identity and private TLS. Select explicit credential mechanisms, not ambient developer credentials. Extend approved provider/identity egress; additive broad policies, arbitrary internet access and platform-secret access are not substitutes. |
| Provider HTTP: `ProviderAdapterRegistry`, `ProviderTarget.bind`, `model_broker/providers.py`, `shared/model_access/{messages,http,provider}.py` | Explicit adapter/protocol/model/capability binding; approved HTTPS origins/routes/headers; bounded bodies/streams/credential refresh; TLS; no redirects or environment proxies. Validate destinations/resolved addresses against SSRF, including IPv6, metadata/private control and rebinding. Preserve guest transport-peer binding. Custom integration means reviewed code/registry configuration, never an arbitrary base URL or tenant Python import. |
| Errors/audit/observability: `ContractError`, `ProviderError`, existing domain exceptions, `shared/api/errors.py`, `shared/errors.py`, broker/control mappings, `shared/audit/{policy,port,vocabulary}.py`, `shared/log_sanitize.py` | Reuse code/category envelopes, bounded stream errors, strict body-free audit, correlation and `Shifter/ModelAccess` metrics. Extend vocabulary/migrations when needed, not an exception tree/audit store. Never reflect Pydantic inputs/paths, SDK exceptions, credential references, prompt/response/tool bodies or unbounded labels. Sanitize before logging; an API envelope cannot undo leaked tracebacks. |
| Guest/adapter/lifecycle: `shared/model_access/credentials.py`, Engine control/credential services, ADR-043 projections, provisioner `model_enrollment.py`, `shifter/shifter_adapter_sdk/model_access.py` | Only scoped enrollment and broker endpoint/aliases cross this seam. Preserve request/operation/generation/epoch and source-network binding. Source selection grants no provider credentials, cloud API rights or control identity to adapters/guests. No invented RAES fields or direct Engine ORM imports. |

## Extension seam and evidence

Extend the **existing** provider target/registry and broker credential resolver
with versioned, discriminated provider/authentication configuration. Keep
hosting/control-workload authentication, inference provider, credential store
and invocation principal independently selected and validated. Two identities
in one project, platform-project Vertex and approved cross-cloud credentials
must fit without editing scenario/CTF policy code. Do not turn the compute
`shared.cloud` factory into an inference registry. New provider IDs require
explicit dispatch; the credential resolver's current non-Vertex-to-Bedrock
fallback must not absorb them.

`ModelAlias.price_schedule_id` and accounting's `_priced_schedule` currently
select one price schedule per alias, not per source. A mixed-provider alias
therefore needs a proven conservative bound covering every eligible shard, or
a versioned extension of the existing price-selection contract pinned to the
allocation. Never apply one provider's cheaper schedule to another provider's
usage. Keep currencies explicit and reject incompatible accounts; no implicit
currency conversion. Credential/quota/account identities must not be derived
from a source's mutable display name or secret version.

Keep client and upstream protocol capabilities distinct. A Messages interface
cannot silently promise OpenAI features it cannot represent. Provider usage,
count geography, prices, caching/reasoning/tool charges, completion horizon and
cancellation require conservative supported bounds. Free-counting pricing is
a current Messages restriction, not a universal provider invariant. Aggregators
such as OpenRouter must pin permitted upstream routing/data policy and disallow
hidden cross-source retries; unavailable billing/routing bounds mean unavailable
integration. Local model tool calls remain data; external execution requires
its own admitted capability.

Reuse `tests/shared/model_access` schema/vectors, Engine allocation/authority/
credentials/accounting tests (including real PostgreSQL contention), CMS
launch/lifecycle and CTF scope tests, broker/control/provider tests, installer/
chart/render/IAM tests and frontend utilities. Required evidence includes:

- Unauthorized discovery/use; concurrent edit/revoke/rotate versus dispatch;
  old replicas and stale cleanup; partial secret-write/publication failures.
- Same-project distinct identities, mixed-provider aliases/weights/shared
  accounts, warm/spare paths, migration/rollback with retained liabilities.
- Secret sentinels absent from read DTOs, errors, logs, audit and rendered
  artifacts; UI defaults, conflicts, denial and credential clearing.

Credential validity, publication, quota availability and live qualification
are separate facts; a connection test does not establish all four. Preserve
`.importlinter`, `scripts/check_layer_imports/layer_imports.yaml`, ADR registry,
generated API/schema inventories, `.github/quality-path-filters.yaml`,
`.pre-commit-config.yaml` and canonical deployment workflows. Required ADR/import
and relevant Terraform/chart/workflow checks supplement CI's full suites;
never weaken them to admit a provider. Live acceptance is GCP only with synthetic
content. Other providers require configured credentials and independent live
evidence; contract tests are not parity. User/operator docs must explain
authority, defaults, live edits, onboarding prerequisites and retained charges.

## Non-goals and prohibited shortcuts

No new gateway authority, generic vault, agent orchestrator, queue/repository
framework, budget system or range lifecycle. No per-range cloud-account
creation, forced separate model project, shared broker/invocation principal,
inferred unlimited budgets, credentials-as-quota or view/adapter round-robin.
No spend resets or automatic retries of potentially billed requests on another
source. No executable provider code from packs, repurposed participant tokens,
weakened dynamic-secret boundary or qualification claims from renders. Private
pack content/evidence and PLAT-215 prompt capture remain outside this change.
