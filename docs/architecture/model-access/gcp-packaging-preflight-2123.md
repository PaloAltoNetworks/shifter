# GCP broker packaging preflight — #2123 / M06

Inspected repository baseline: `613f365ac`, 2026-09-12. This note applies
[ADR-059](../../adr/059-range-model-access-broker.md), the [security
contract](security.md) and [operations contract](../../ops/model-access.md)
to the current repository. It is guidance, not an implementation plan or
evidence of a deployed boundary. The ADRs remain proposed.

M06 owns deployment identity, packaging and private reachability. M01's
`shared.model_access` contracts exist; the broker/control server belongs to
M05, the Vertex adapter to M07, enrollment to M08 and deployed boundary proof
to M10. Infrastructure may land disabled before those consumers, but must
not report ready with a placeholder server, fabricated grant or paid probe.

## Repository integration gaps

These are constraints on the intended implementation, not defects repaired
by this documentation change.

| Existing boundary | Consequence for M06 |
| --- | --- |
| `platform/charts/shifter/templates/networkpolicies.yaml` selects every platform pod for provider-API and private-service egress (PostgreSQL and both Redis ports). | NetworkPolicy allows are additive. A broker-specific restrictive policy cannot subtract these permissions. Make the incumbent broad selectors exclude the broker while retaining existing consumers; assess the union of all rendered policies. Keep default denies and the controlled DNS path. |
| `installation.contract.ProcessRole` has only portal, worker, provisioner and range-task; `bundle_gcp._gcp_output_roles()` assigns every generated key to portal/worker. | Give the broker an explicit consumer in the existing output contract/inventory. Do not label it a worker or grant it the shared `platform-runtime` environment. Regenerate contract publication and extend runtime-role parity tests when that vocabulary changes. |
| `entrypoint.sh` eagerly hydrates application secrets; `config/_model_access_settings.py` imports Django and binds the catalog at import time. | Sharing the attested application image requires a dedicated broker executable that bypasses the application entrypoint/full settings. Reuse the catalog parser/digest semantics through a Django-free loading seam; do not copy that loader or import all settings merely to reuse it. |
| `gcp_range_cell_firewall._reject_denied_egress_overlap()` rejects private/management destinations in ordinary allow-CIDRs. | A private broker VIP cannot ride `GCP_RANGE_EGRESS_ALLOW_CIDRS`. Extend the existing egress contract with the explicit broker capability, realized as an exact destination and port; preserve the generic overlap rejection and public-web complement. |
| `scripts/bootstrap/gcp_control_plane.py` renders/deploys Helm; `deploy.yml` calls `_gcp-dev.yml`, which applies `platform/k8s/gcp/overlays/` with Kustomize. | A chart-only change is not the deployed CI path. Make the broker artifacts consumed by the real deployment lane from the canonical chart/runtime inputs, with explicit resource ownership; compatibility projection must not become a second hand-maintained broker manifest. A general deployment migration is outside M06. |
| `scripts/gcp/verify_running_image_ids.py` has closed component/container/deployment maps; `_helm_image_values()` accepts exactly three application image identities. | Register the optional broker in release convergence and image evidence using validated enablement. Reusing the platform digest need not invent a fourth image. If a separate image is selected, extend the build, scan, SBOM, provenance and image-shape consumers together. Never ignore unknown workloads to accommodate it. |
| `scripts/check_tf_gcp_iam_resource_scope` recognizes four workload keys and existing secret/storage rules. | A new broker name or impersonation grant is not automatically protected. Extend the incumbent checker and negative fixtures to inspect broker/shard identities and exact-target token issuance, including equivalent custom permissions. |

## Configuration, identity and process gates

The following layers must agree on the same deployment-owned inputs.
Validation at distinct trust boundaries is intentional; independently
maintained policy schemas or semantic rules are not.

| Layer and canonical incumbent | Required satisfaction |
| --- | --- |
| Root YAML: `shifter/installation/loader.py`, `schema.py`, `settings_gcp.py`, `model_access.py` | Preserve duplicate-key rejection, root/backend/shared-settings dispatch and aggregated `ConfigIssue`/`InstallationConfigError`. `settings.model_access` currently permits only `enabled` and `catalog`; packaging fields cannot be inserted ad hoc. Place deployment transport configuration in the owning installation schema, leaving policy semantics with `shared.model_access`. |
| Catalog: `shared/model_access/{core_models,models,catalog,digest,provider}.py` and generated `installation/published_contract/model-access-policy.v1.schema.json` | Reuse closed DTOs, reference validation, canonical digest, duplicate-member JSON parser and bounded provider result categories. Publish schema from the existing generator and conformance vectors, never edit a second policy schema in Helm or Terraform. SDK credentials and arbitrary origins are not catalog values. |
| Runtime artifact: `installation/render.py`, `runtime_inventory_gcp.py`, `bundle_gcp.py`, `contract/_outputs.py`, `scripts/gcp/render_runtime_env.py` | Render a bounded catalog file and path/digest, not inline policy JSON or credentials in env. Mount the actual artifact read-only at the advertised path for each intended consumer; bind its digest to the rollout. Preserve `OutputSensitivity`/destination restrictions and use an explicit broker-only key inventory. Validate booleans, paired fields, hostname/audience/ports and newline/NUL-free env values; a digest/path alone does not prove a mounted catalog. |
| Runtime loading | Retain the current 2 MiB catalog bound, duplicate rejection, semantic validation, digest comparison and fail-closed enabled/disabled consistency. The broker loading seam must remain usable without Django initialization. Disabled defaults render no broker Deployment, listener or new invocation/impersonation grant; explicitly enabling an incomplete/unsupported backend configuration fails validation. |
| Terraform: `platform/terraform/gcp/modules/platform-core`, `portal/iam`, `portal/secrets`, `portal/vpc`, `range/vpc`, `project-services` and environment roots | Carry typed inputs and owning-module outputs all the way through bootstrap/runtime rendering. Use a bounded map of approved model project/target GSA references, with stable identities and explicit deployment ownership. Model/billing projects, compute project, platform project and the dedicated dynamic-secret project remain distinct even when an allowed pair of configured values coincides. Terraform validates deployment shapes; it does not allocate ranges or reproduce catalog policy. |
| Cloud IAM and onboarding: `portal/iam` workload/resource matrix | Dedicated broker KSA/GSA with exact namespace/KSA binding; no node-identity fallback, cross-deployment principal, portal/worker invocation grant or participant guest SA. Select direct, exact-target shard impersonation as ADR-059 specifies. Check target existence, ownership, effective inherited IAM, API/billing/model availability, region and required invocation/count permissions before enabling a shard. No project-level token creator, key admin, `actAs`, wildcard delegation chain, broad `aiplatform.user`, or IAM mutation rights for the broker. Do not copy incumbent self-signBlob or legacy range-Vertex key grants. |
| Kubernetes and process: chart `values.schema.json`, `_helpers.tpl`, service accounts, Deployment and runtime ConfigMaps | Keep provider-neutral defaults, digest-pinned image and restricted pod/container contexts. A non-root process can terminate TLS on an unprivileged container port behind Service port 443; do not grant root or extra capabilities to bind 443. No host networking, host paths, privileged sidecar, shell-generated secret argument, inherited portal `envFrom`, database secret, or Kubernetes mutation RBAC. Prove the resulting process env/import closure as well as rendered YAML. |
| Secret material: `portal/secrets`, existing bootstrap secret synchronization, `entrypoint-lib.sh`, `shared.cloud` secret adapters | GCP model identity is keyless. TLS private keys use an exact broker-only secret reference and restricted read-only mount; values must not enter Terraform resources/state, Helm values/release history, ConfigMaps or generated config. Reuse stdin/protected temporary-file transport patterns without running the portal hydration bundle. Future provider-secret references must use the owning secret inventory and exact IAM; never the range-readable dynamic-secret family. |
| Host/OS and diagnostic surfaces | Tokens, authorization headers and private keys stay out of argv, shell tracing/history, image layers, operation JSON, startup metadata and support artifacts. Probe clients consume credentials through protected descriptors/files or in-process SDK calls, not `curl -H` token arguments. Bound temporary storage and prevent core/body dumps. `shared/cloud/sensitive_env.py` classifies provisioner env, not arbitrary broker payloads; pointer suffixes do not make secret-bearing URLs safe. |
| Authentication/control: existing Engine service facade, `shared/api` and model-access protocol contracts | M05 implements the separate private control listener and validates signed workload identity (issuer, exact audience, subject, expiry) over verified TLS. Participant capabilities, portal sessions/API tokens and provider access tokens are different credential classes. Package only the narrow listener; no public Ingress route or broker permission to enroll arbitrary grants, mutate ranges or alter budgets. Network location alone is not authentication. |
| Error/observability: `shared.errors`, `shared/api/errors.py`, `shared/cloud/exceptions.py`, `config/logging.py`, `shared/audit`, provisioner `log_redact.safe_log_fingerprint` | Reuse authored safe messages, existing cloud exceptions at cloud-adapter boundaries and model-access closed provider results. M05 adapts the safe semantics to the client protocol; no new public exception family or forced DRF/Django startup in the broker. Allowlist bounded metadata for ECS logs/metrics/audit; do not log SDK exception strings/chains, HTTP bodies, credentials or raw config. Unknown field names, parser paths and client request IDs can themselves contain hostile/secret text: bound/sanitize them and use broker-generated correlation IDs. The existing formatter is not a redactor. |

The [Google impersonation contract](https://docs.cloud.google.com/iam/docs/service-account-impersonation)
requires `iam.serviceAccounts.getAccessToken`; the predefined token-creator
role also has other authority. Qualify the minimum supported permission set
on each exact target, and keep broker-to-Engine ID-token issuance separate
from shard access-token minting. Effective IAM checks must include inherited
grants, not just this module's resource list.

## Network realization and operational constraints

- The existing `installation/range_egress.py` vocabulary owns `status-quo`,
  `allowlist`, `deny-all` and strict `none`. Workspace selection, CMS resolution,
  Engine's pinned `Range.egress_mode`, operation DTO/projection and provisioner
  rendering carry that posture. Extend these adapters only where the broker
  capability crosses them; do not add a second mode enum or infer enrollment
  from a global VIP. Required external-model access with strict `none` is
  incompatible; optional access stays unavailable. A declared broker effect
  must not be advertised as zero external effects.
- Account for both deployment `range/vpc` firewall/NAT rules and per-range
  `gcp_range_cell_firewall.py`, `gcp_range_cell_plan.py` and `raes_gcp_plan.py`
  realization. The latter retains a Private Google Access lane independently
  of general egress denial, and has a preprovisioned-firewalls bypass. Neither
  is broker-only isolation evidence. Qualify that path or reject it for model
  clients; do not silently widen Google API access. Preserve management/peer
  denies, intra-range traffic and no-NAT behavior for strict `none`.
- One owning deployment output supplies the reserved private VIP, hostname,
  TLS identity and admitted network reachability. The exact VIP:443 exception
  applies only to admitted range targets. Check both directions, firewall
  priorities, routes/peering, LB health checks and direct node/Pod paths.
  Keep range DNS resolution on the existing controlled resolver path; a new
  hostname must not require general external DNS or guest Google API access.
- Use the ADR-059 internal passthrough Service and source-preserving local
  backend routing. The broker compares the transport peer to Engine's trusted
  subnet binding for the current allocation/generation, never an organizer
  CIDR or `X-Forwarded-For`. Verify `canIpForward=false` on model client VMs.
  The existing OpenVPN gateway intentionally enables forwarding; it is not a
  model-client template or a qualified substitute source. Test from root in
  two ranges, including spoofed headers, stolen tokens and direct backend paths.
- `portal/gke/main.tf` selects Dataplane V2. Broker-to-Engine policies select
  exact workloads/namespaces and ports, not Pod/Service `ipBlock` addresses.
  Preserve only the qualified DNS, telemetry, provider and identity paths.
  Workload Identity needs a narrowly scoped GKE metadata-server path; that
  credential-transport exception does not authorize participant-controlled
  URLs to reach metadata. Pin the actual cluster/version behavior in evidence.
  See [GKE NetworkPolicy requirements](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy).
- NetworkPolicy CIDRs cannot enforce provider hostnames or HTTP methods.
  Reuse `portal/vpc` controlled Google API DNS/routes, with the adapter's
  approved origin/method/model allowlist, TLS validation, redirect rejection
  and connection-time address checks. Private provider VIPs need explicit
  validation rather than a blanket private-address exemption. Identity API
  origins are trusted SDK configuration, never request-supplied URLs.
- Range placement already supports multiple regions. Make permitted ingress
  regions/global-access behavior an explicit deployment setting, consistent
  with residency policy; do not assume a regional VIP reaches all admitted
  ranges or select `global` model routing to fix connectivity. The default
  internal LB reachability is regional; verify the selected setting against
  [GKE Service parameters](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/service-load-balancer-parameters).
- Keep TLS ownership explicit: issuer/renewal operator, DNS/SAN/trust bundle,
  secret reference, expiry alert, renewal overlap and rollback. Define whether
  the listener reloads projected key/cert updates or drains on rollout; never
  assume a mount update means a running TLS context reloaded. Avoid `subPath`
  for live-rotated material. CA rotation also requires guest/control trust
  overlap, not just server certificate replacement. Do not reuse the public
  portal's managed ingress certificate mechanism for passthrough termination
  or introduce a mandatory mesh/certificate platform.
- Reuse chart resource/security/anti-affinity helpers and the operations
  contract's two-replica qualification target, disruption budget and bounded
  connections/buffers. Service endpoints must stop new traffic during drain;
  termination grace includes endpoint withdrawal, the admitted request bound
  and settlement attempt. M05 owns dispatch/continuation fencing. No paid
  liveness/readiness prompts; provider failure must not cause restart storms.
  Catalog, control identity or certificate failure leaves admission unavailable.

## Evidence, workflow and ownership

Use the existing Helm contract suite, bootstrap/runtime renderer tests,
installation/schema-publication and runtime-role parity tests, GCP IAM
checker fixtures, per-range firewall/plan tests and
`scripts/terraform/tests/test_range_zero_egress.py`. Negative cases must
exercise the rendered/planned graph: inherited broad policy selectors,
foreign/wildcard target impersonation, missing/mismatched catalog mount,
secret sentinels, disabled/unsupported settings, strict `none`, wrong VIP/port,
forwarding clients, and attempted Job command/env/identity widening. Include
intentional GCP render-digest updates and unchanged disabled AWS behavior.

Preserve `shared/cloud/gcp/task_runner.py`, `engine/ecs.py` forwarding,
`sensitive_env.py`, chart/static `validatingadmissionpolicy-provisioner-jobs`
and `tests/platform/test_gcp_job_launcher_manifests.py` parity. A broker
Deployment has probes/its own command; that is not permission to relax the
provisioner Job's command/probe/volume/env restrictions. If an exact non-secret
capability reference crosses a Job later, every owning contract must agree.

New production paths need real lint/security/test owners in
`.github/quality-path-filters.yaml`, consumed by `scripts/quality_ownership`
and `_quality.yml`; also inspect `deploy.yml` change filters, `_gcp-dev.yml`
preflight/provenance/convergence, `.pre-commit-config.yaml`, `.importlinter`,
`.kube-linter.yaml`, `.tflint.hcl`, Checkov and ADR guard checks. Update ADR
enforcement documentation with guard changes; no new skips or parallel CI
classifier. Preserve the canonical repository/workflow and Ground Control
traceability conventions; M06 does not close the full PLAT-202 capability.

Implementation verification includes ADR guard; Terraform fmt/validate,
TFLint, Checkov and IAM tests; Helm lint/render and contract tests;
kube-linter/kubeconform on actual rendered artifacts; import-linter for
platform changes and actionlint for workflow changes. A base-directory lint
alone does not check an enabled broker. M06 supplies reproducible positive
and negative probes and binds rendered evidence to config/catalog digest,
image/provenance, IAM targets and network topology. M10 owns the deployed
source-preservation, effective-permission, revocation and rotation proof.
Record synthetic and live results separately; this preflight ran none of
those live tests.

## Extensibility and non-goals

The next model project, shard identity, model alias or ingress region belongs
in typed deployment maps/catalog revisions, not another Terraform resource
copy, Helm literal or shell modulo allocator. Keep transport settings
(VIP/hostname, workload identity, control audience, TLS references, qualified
regions and resource/drain bounds) separate from immutable policy and
per-range authorization. Unsupported providers remain disabled until their
own adapters and boundary evidence exist.

Engine continues to own durable allocation, grants, quota/budget accounting,
reconciliation and PostgreSQL transactions through its existing services,
capacity records, operation generations and durable outbox/audit patterns.
The broker has no ORM, database credentials, Redis authority or new ledger.
M06 does not implement scenario/RAES fields, CTF capacity policy, allocation,
request accounting, broker protocol/auth handlers, Vertex invocation, guest
enrollment, management UI, legacy-key removal, multi-cloud parity, external
tool execution or prompt capture. It must not create per-range model projects,
share participant tokens to share capacity, equate IAM identity with quota
pools, or use direct guest credentials as an outage fallback.
