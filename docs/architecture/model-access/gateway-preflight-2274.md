# AI gateway replacement preflight — #2274

Architecture guidance, 2026-10-12; inspected baseline `4f2272731`. The maintainer's
[replacement-evaluation clarification](https://github.com/Brad-Edwards/shifter/issues/2274#issuecomment-6131352734)
supersedes #2274's conditional deferral and broker-improvement outcome. This run
has no formal requirement. The
[replacement evaluation](gateway-replacement-evaluation-2274.md) records product
fit, the 2026-10-13 LiteLLM OSS selection and the proposed integration. Rotation
uses documented key create/delete APIs through existing lifecycle automation and
secret delivery, with bounded overlap and stable native budget ownership. Paths
below omit `shifter/shifter_platform/` for
platform modules; other paths are repository-relative.

## Starting posture and evaluation scope

[ADR-068](../../adr/068-model-access-broker-parked.md) parks the broker, prohibits
hardening or extending it beyond CI maintenance, and makes ADR-064's keyless
direct access the only supported guest model path. ADR-059 through ADR-061 and
ADR-067 are superseded history. In particular, ADR-067's LiteLLM selection is not
a current adoption decision. Existing broker code and tests are reuse candidates,
not proof of a supported deployment or permission to reactivate it.

ADR-068 records certificate renewal, first-deploy ordering and mandatory-limit
defects. The maintainer has decided to replace the broker and requested an
evaluation of maintained options, including LiteLLM. These recorded failures
are the evaluation rationale; they do not supply a current measured workload,
scale or supported-deployment reproduction. Do not invent those measurements,
enable the parked broker for evidence, or present product documentation as live
qualification. Runtime adoption and a guest-path switch remain separate work.

Before rollout, qualification needs the pinned client/protocol/provider,
expected and observed behavior, concurrency/throughput/latency envelope and
operating impact. Distinguish recorded historical defects from current supported
behavior. Keep private operational evidence with its owner;
use synthetic, body-free reproductions in this repository and public metadata.

Compare maintained gateway products against the ADR-068 operating intent, using
current primary documentation and explicit maintenance snapshots:
protocol/features, identity and credential custody, usage/pricing and spend
enforcement, fixed routing/data location, security and dependency provenance,
resource/availability demands, automatic credential renewal, fresh bootstrap,
and migration/rollback cost. Improving the broker is rejected by the current
decision. Product popularity or a generic vendor-switching interface is not
evidence. The proposed gateway integration must
name the smallest integration, ownership and acceptance tests before follow-on
implementation issues; it must not create two authorities or competing paths
for the same admitted workload.

The clarification resolves the old issue's contract tensions as follows:

- **Spend:** configured limits remain an optional capability; ADR-068 defaults
  future controls to absent, and direct access has no broker spend enforcement.
  Specify which
  workflows require caps, their scope and failure behavior, and how configured
  caps survive either outcome. Absent limits cannot be silently turned into
  mandatory finite limits, zero limits or large numeric sentinels. Alerts,
  provider quotas and post-hoc usage are not equivalent to request admission.
- **Custody and migration:** the future proxy holds provider credentials;
  ADR-064 guests obtain short-lived provider tokens from metadata. No durable
  provider keys are delivered, but this is not mediated credential custody.
  Preserve the current supported posture during assessment and explicitly
  decide the guest cutover separately. A proxied workload must not retain a direct
  identity/egress bypass or fall back to it on proxy failure.

Where a cap is configured, reserve a conservative bound before billable effects
and fail closed when its authority or pricing is unavailable. Provider execution
may continue after transport cancellation; an application admission ceiling is
not a guarantee about the eventual cloud invoice.

## Existing boundaries a justified design must pass

This preflight changes no runtime boundary. The following identify incumbent
owners and protections for a later authorized integration, not instructions to
revive the parked broker's membership/freshness machinery or duplicate a vendor's
native keys, codecs or accounting. Historical broker-specific contracts stay
unchanged for retained records. Replacing their runtime authority requires an
explicit migration decision, described in the evaluation.

| Cross-cutting layer and canonical incumbents | Required passage |
| --- | --- |
| Management UI/API contracts, if changed: `frontend/src/api/{client,csrf,queryClient,errors,model-sources}.ts`, generated `schema.d.ts`, `shared/api/contract.py` | Reuse same-origin session/CSRF, typed API errors, tenant-scoped queries and zero automatic mutation retries. Handle revision conflicts explicitly; credential forms remain transient/write-only, with no browser storage or query-cache persistence. Regenerate the existing contract rather than hand-copying DTOs or adding another fetch client. |
| Tenant administration and source use: `cms/api/model_sources.py`, `cms/services/_model_source_selection.py`, `workspaces.services`, `shared/api/{permissions,principals}.py`, `shared/api_tokens` | Reuse session/CSRF, object/tenant authorization and locked owner-service checks. Registration does not confer spending authority. Any admitted API token needs registered scopes plus live domain authority; failed bearer authentication cannot fall through to a session. Model clients, portal users, provisioners and control workloads are distinct principals. |
| Parsing and shared schemas: `shared/api/strict_json.py:ClosedJSONParser`, `cms/api/preparation_adapters.py:PreparationSerializer`, `shared/model_access/{core_models,messages,catalog,digest,sources,control_wire}.py` | Preserve raw byte/depth/duplicate-key/non-finite checks, closed request DTOs, semantic reference validation and digests; validate private replies too. Reuse canonical models rather than another gateway policy DTO/parser. Follow the existing deliberate response-field compatibility rules; do not indiscriminately widen request or billing shapes. |
| Installation and runtime configuration: `shifter/installation/{schema,loader,model_access,model_broker_runtime,gcp_model_broker,aws_model_broker}.py`, `config/_model_access_settings.py`, `shared/model_access/runtime.py` | Evolve all closed consumers together, with exact inventory/identity readback and path/digest binding. Generate installer schemas through `scripts/generate_model_access_schema.py`; preserve old versions' meanings. Deployment v3 policy and Engine's v4 source overlay are different scopes. The installer accepts v1–v3 and requires enabled v3 for broker execution; do not feed it a v4 allocation overlay. Its GCP/AWS inventory checks are narrower than code-level provider support. The 2 MiB runtime catalog ceiling does not override the combined 96 KiB ConfigMap transport budget. |
| Environment and host/OS: `BROKER_RUNTIME_ENV_KEYS` in `shifter/installation/gcp_model_broker.py`, installer `runtime_inventory{,_gcp,_aws}.py`, `scripts/gcp/{render_runtime_env,render_model_broker}.py`, chart values/schema/templates, `shared/cloud/sensitive_env.py` | Carry approved references/paths/digests through each allowlist and renderer. No credential bytes in argv, shell interpolation, environment literals, ConfigMaps, Terraform state, images, subprocess output or CI/support artifacts. Use restricted read-only mounts and ephemeral credential resolution; retain chart `_helpers.tpl` non-root, read-only filesystem, seccomp and dropped-capability settings. The standalone process cannot inherit portal `envFrom`, secret hydration, DB credentials or field-encryption keys. Env-name classification is defense in depth, not authorization. |
| Secret custody: `shared/model_access/{source_credentials,provider_runtime}.py`, `engine/services/_model_source_control.py`, `shared.cloud` secret stores/owned names, `model_broker/provider_credentials.py` | Reuse write-only administration, tenant-owned immutable versions and bounded acquisition. Prefer keyless exact-target impersonation; source references are not permission to read arbitrary secrets. Read outside DB locks, then reauthorize. Private `SourceExecutionProjection` is ephemeral and secret-bearing, never a public read DTO. Reuse bounded token refresh/cache behavior without creating another secret store or leaking SDK exceptions. |
| Listener/authentication/network: `shared/model_access/{http,network,control_identity,workload_identity}.py`, `model_broker/server.py`, `engine/model_access_control`, chart broker/control/egress policies | Preserve private verified TLS, explicit private pod binding, bounded HTTP framing and separate control identities. GCP control verifies immutable subject as well as email/audience/signature. Existing guest grants bind actual socket peers, operation/generation/epoch and current authority; forwarded headers are not identity. A different gateway credential mechanism needs explicit review, not a bypass of these checks. Assess the union of additive NetworkPolicies and effective range egress, not one manifest. |
| Provider routing and billing: `ProviderTarget.bind`, `ModelProviderAdapter`, `ProviderAdapterRegistry`, `model_broker/{providers,provider_usage,openai_messages,egress_proxy}.py` | Bind logical aliases to approved provider/model/version, geography and identity. Preserve fixed origins/routes, TLS, explicit proxies, DNS/address validation, bounded streams and no redirects/environment proxies/hidden retries or failover. OpenRouter already pins its upstream and disables fallback. Protocol translation is not full OpenAI/Anthropic feature parity. Local tool content is data, not tool-execution permission. Qualify all admitted billable features, usage and cancellation semantics. |
| Persistence, budgets and workflow: Engine `_model_sources`, `_model_allocation*`, `_model_policy_transition`, `_model_request_{accounting,commit,lifecycle,reconcile}`, models `_model_{sources,allocation,budget}`, CMS/CTF owner services | Reuse immutable revisions/CAS, source-use fences, canonical row-lock order, PostgreSQL constraints, integer money/currency, pre-dispatch applicable-account reservations and strict audit when controls are enabled. v4 pricing already resolves the selected shard's immutable schedule. Physical quota, aliases, credentials and budget accounts are different identities. Keep original liabilities on edits/rotation; unknown dispatch is neither a refund nor permission to retry. No second lifecycle, ledger, repository layer or gateway DB writer over Engine tables. Any replacement of authority needs an explicit migration decision rather than dual accounting. |
| Errors, audit and observability: `ContractError`, `ProviderError`, broker/control mappings, `shared/api/errors.py`, `shared/errors.py`, `shared/audit`, `shared/log_sanitize.py`, `shared/model_access/diagnostics.py` | Reuse bounded authored codes/categories, request correlation and body-free audit/structured `Shifter/ModelAccess` telemetry. Keep public API, private control and Messages/SSE error envelopes distinct. Normalize before logging; suppress dependency wire diagnostics even under DEBUG. No prompts, completions, tool bodies, credentials, body hashes, raw provider/Pydantic errors or unbounded labels in logs/traces/evidence. Gateway logging/callback defaults and provider retention require explicit review. |
| Guest lifecycle and deployment: ADR-043 projections/outboxes, `shifter/engine/provisioner/{model_enrollment,gcp_range_vertex_creds}.py`, `shifter/shifter_adapter_sdk/model_access.py`, `scripts/bootstrap`, `.github/workflows/_gcp-dev.yml` | Keep existing operation generation and public SDK boundaries; no scenario-provided URLs, imports, keys or invented RAES fields. Enrollment uses verified SSH stdin/tmpfs, not persisted SSM commands or argv. Any future proxy must bootstrap without manual trust objects and renew credentials automatically. The current trust-before-cluster ordering is a recorded gap; public edge managed certificates do not establish private listener renewal. Drain/recovery/rollback must preserve liabilities and cannot resurrect revoked credentials. |

Same-project Vertex remains valid: project equality does not merge broker,
invocation, compute, quota or dynamic-secret authority. Use the owning Terraform
IAM modules (`platform/terraform/gcp/modules/{platform-core,portal/iam}`), the
existing `scripts/check_tf_gcp_iam_resource_scope` checker and exact-resource
readback/probes. Do not add broad project/secret grants, ambient developer
credentials, per-range projects or a rule requiring a separate model project.
AWS transport/IAM and other providers require independent qualification.

## Extension seam, evidence and boundaries

The existing source-description seam is `ProviderTarget` plus revision-pinned
source configuration. Translate approved targets into the selected product's
native configuration; do not build a second Shifter provider registry or carry
the parked broker adapters into the replacement process. Parameterize approved
project/account, inference/count geography, model/version and authentication
there, independently of compute hosting and secret-storage ownership. A second
approved model/project should not require scenario, CTF or accounting branches.
Gateway-specific translation, if justified, stays at that transport/config
boundary; there is no current acceptance for a generic replaceable gateway
framework. Optional controls need an explicit versioned representation at the
canonical policy boundary: changing `AccessLimits` or interpreting existing v1–v4
finite fields as unlimited would change historical accounting semantics.

Reuse `tests/shared/model_access` contract/schema/provider/privacy/TLS suites,
Engine real-PostgreSQL accounting/source/authority tests, CMS/CTF lifecycle/scope
tests, installer tests, chart tests, and bootstrap/GCP renderer/IAM/probe tests.
The later decision's acceptance must cover supported client JSON/SSE behavior,
same-project IAM, unauthorized tenant/control access, secret sentinels across
errors/logs/artifacts, configured cap contention, ambiguous dispatch/disconnect,
fresh bootstrap, renewal, drain/restore and migration without bypass. Keep safe
synthetic local evidence separate from authorized live operating evidence;
health checks, rendered manifests and mock responses are not qualification.

Whole-repository constraints remain `.importlinter` (especially broker isolation),
`scripts/check_layer_imports/layer_imports.yaml`, ADR registry/exceptions,
generated API contracts and installer/chart schemas, `.shifter.yaml` loading,
backend runtime inventories, Terraform IAM/network/project-service modules,
Helm templates, Packer/client/image pins, canonical bootstrap/deploy workflows,
`.github/quality-path-filters.yaml`, `.pre-commit-config.yaml`, and Makefile gates.
Architecture changes require `python3 scripts/adr_guard/adr_guard.py --all --level ci`;
source/import, Terraform, workflow and Kubernetes changes also require their
applicable native checks. Do not weaken a gate to admit a gateway.

Non-goals of this preflight are runtime implementation and provider adoption,
broker activation/hardening/removal, new implementation issues, a parallel
inference path, vendor-swapping contracts, new auth/token/validation/error/audit
frameworks, prompt capture or new hosting/data transfers. This preflight does not
claim live qualification; the evaluation addresses the clarified comparison and
proposed replacement decision.
