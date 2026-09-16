# GCP range-secret project boundary preflight (#1586)

Issue #1586 closes the design gap left by #1517 for provisioner-created
Secret Manager resources. Issue #2083 implements this architecture contract
across Terraform, installation config, runtime projection, all dynamic writer
families, migration teardown, static-input IAM, permission probes, and operator
documentation.

## Repository finding

The issue context says #1517 landed an optional `dynamic_secret_project_id`
Terraform/runtime seam. The current repository does not contain that input,
output, setting, or runtime key. The same-project residual grants in
`platform/terraform/gcp/modules/portal/iam/main.tf` still target
`var.project_id`, and every dynamic-secret writer still resolves the platform
project directly or receives a project with another meaning. The seam is
therefore required work, not an incumbent that implementation may assume.

## Google authorization basis

The design relies on two current Google Cloud authorization facts:

- [`projects.secrets.create`](https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/create)
  authorizes `secretmanager.secrets.create` on the request's `parent` project;
  `secretId` is a separate request field. A condition over the not-yet-created
  secret name therefore cannot bound creation.
- [Secret Manager IAM](https://cloud.google.com/secret-manager/docs/access-control)
  supports conditions over secret and secret-version resource attributes, so
  existing-secret operations can be constrained by name. The
  [IAM Conditions attribute reference](https://cloud.google.com/iam/docs/conditions-attribute-reference)
  recommends coupling `resource.name` checks with the intended
  `resource.type`; the implementation's prefix conditions must follow that
  fail-closed shape.

## Decision

Use one dedicated range-secret project per Shifter deployment. The project is
the security boundary for all provisioner-created ephemeral secrets. It must
not be shared by unrelated deployments or customers, and it must not contain
platform runtime bundles, operator bootstrap secrets, application data, or
Terraform state. This follows ADR-054: a deployment is the customer security
and administration boundary; organization and workspace rows are internal
authorization scopes, not cloud-project isolation units.

Do not use a project per range, user, organization, workspace, or operation.
That would add project quota, billing/bootstrap, eventual-consistency, cleanup,
and lifecycle coupling to the range path. Do not use one global range-secret
project across deployments, because that would merge workload identities and
the create blast radius across customer boundaries.

A creation broker is not selected. It could validate every requested secret ID and
remove `secretmanager.secrets.create` from the provisioner, but it would also
introduce a new authenticated API, availability dependency, idempotency and
retry protocol, deployment unit, persistence question, and error surface. The
dedicated project achieves the required creation boundary using the existing
Secret Manager clients, provider-native references, and Workload Identity. A
broker can consume the same project and naming contract without changing
persisted secret references if a new architecture decision selects one.

The dedicated project is a pre-existing deployment prerequisite owned by the
cloud/bootstrap layer that has organization and billing authority. Application
runtime code must never create or delete GCP projects. The platform Terraform
root consumes its project ID, enables Secret Manager through the existing
`modules/project-services` module, and owns the cross-project IAM bindings. A
Terraform destroy must not destroy the project or its live secrets; project
retirement is an explicit post-drain bootstrap operation.

## Resource and IAM boundary

New dynamic secret IDs created after the dedicated-project boundary is active
must share one root grammar:

```text
shifter-{environment}-dynamic-{audience}-{family}-{scope}-{purpose}[-{stable-digest}]
```

`environment` comes from the validated deployment/runtime contract, never a
hidden production default. The runtime naming helper requires it explicitly
and accepts only lowercase alphanumeric words separated by single hyphens, so
its name prefix cannot drift from Terraform's IAM prefix through normalization.
`audience` is a closed authorization partition:
`participant` only for credentials whose full references are published through
an established participant access channel, and `workload` for every other
dynamic secret. `family` distinguishes guest, RAES, GDC VM Runtime, VM-Series,
Vertex, and VPN material. Family-specific suffixes may remain, but all IDs
created in the dedicated project must start with the exact deployment prefix
`shifter-{environment}-dynamic-`. Name parts must use one dependency-light
provisioner naming helper, the existing Secret Manager character/length rules,
and a stable digest when truncation could otherwise collide. Labels may aid
inventory but are not an authorization boundary.

The existing names are migration aliases only:

- `shifter-range-{range_id}-...` from `gcp_guest_secrets.py`,
  `gcp_range_vertex_creds.py`, and `vpn_secrets.py`;
- `shifter-{environment}-range-{range_id}-...` from `_gdc_vm_naming.py`; and
- `shifter-{environment}-ngfw-user-{user_id}-...` from
  `gdc_vmseries_common.py`.

Do not add another family-local sanitizer or prefix. The shared naming leaf is
the one justified new abstraction: no current helper owns all dynamic-secret
families, and importing a full lifecycle module merely to reuse a private name
function would invert dependencies.

The dedicated project IAM graph is:

| Principal | Scope | Permission contract |
| --- | --- | --- |
| Provisioner GSA | Dedicated project parent | One deployment-local custom role containing only `secretmanager.secrets.create`. This binding cannot be resource-name conditioned because Google authorizes create on the parent before the secret exists. |
| Provisioner GSA | Dedicated project, conditioned on the canonical deployment prefix and the intended Secret Manager resource types | The exact existing-secret verbs exercised by the clients: delete secret, add/access versions, and set IAM policy where Vertex and VPN attach range-host/gateway readers. Do not grant predefined `roles/secretmanager.admin`. |
| Portal GSA | Dedicated project, conditioned on the intended Secret Manager resource types and the canonical `shifter-{environment}-dynamic-participant-` audience prefix | Read-only secret/version access needed by the established SSH, RDP, participant-account, VM-Series, and OpenVPN-profile resolution paths. It must not cover Vertex keys, VPN issuer/server material, bootstrap/directory material that is not participant-published, or any future family by default. No create, version mutation, delete, or IAM-policy permission. |
| Range Vertex host and OpenVPN gateway GSAs | Individual secret | Preserve the provisioner-owned per-secret `roles/secretmanager.secretAccessor` policy. Never grant participant-controlled range hosts project-wide access. |

Custom roles must be assembled from the operations actually used by the five
writer families; permissions are not copied from `roles/secretmanager.admin`.
Create the project-level custom roles in the dedicated project and reference
their target-project role names; a similarly named role owned by the platform
project is not the same authority. The Terraform/bootstrap deployer therefore
needs bounded role-definition, IAM-binding, API-enablement, and audit-config
authority in the supplied project, but no runtime workload receives those
control-plane permissions.
The unconditioned create role is acceptable only in a project whose sole
purpose is dynamic range secrets. Prefix conditions remain mandatory for every
operation against an existing resource. Each condition must also constrain the
Secret Manager resource type so adding a permission for a different resource
type cannot silently broaden the binding.

The parent-scoped create grant has one unavoidable residual: the provisioner
can create an empty Secret resource with an arbitrary ID inside the dedicated
project. It cannot add/access a version, mutate IAM, or delete that resource
unless its name also passes the existing-resource condition. Therefore the
negative creation guarantee is **no creation in the platform or any unrelated
project**, not an impossible claim that `secrets.create` is prefix-restricted
inside the dedicated project. Treat empty-resource garbage/quota exhaustion as
a bounded denial-of-service residual: monitor it and give only the
bootstrap/operator cleanup identity the ability to remove an out-of-prefix
probe or abandoned object. Do not give the provisioner `list` or an
unconditioned cleanup permission to hide this limitation.

The portal condition must not use the deployment root prefix as its whole read
boundary. The shared naming leaf owns a closed credential-class enumeration and
maps each class to its audience, family, and purpose. Family writers supply only
that class and the resource scope; they cannot select `participant` directly.
An unknown class fails closed, and adding one requires a central classification
whose default posture is `workload`. Terraform derives the single participant
prefix from the validated environment rather than copying a second list of
readable families. A credential class may be classified `participant` only when
its full reference is admitted into an established participant access channel.
Authorization must not be inferred from a suffix in a portal reader or
duplicated across family-local helpers.

During migration, the legacy portal condition is the narrow exception: it
composes each established legacy prefix with only the credential shapes that
prefix actually published. The broad `shifter-range-` family admits
`-participant-ssh`, RDP, OpenVPN profile, and authored RAES account material;
an explicit supported `resource.name.extract(...)` classification excludes the
`shifter-range-{range}-raes-domain-...` directory namespace even though one of
its purposes also ends in `-account-password`. The environment-scoped GDC and
VM-Series prefixes admit only their established SSH/RDP shapes. The source
checker parses and locks this full composition and rejects an expanded binding
above Google IAM's hard limit of 12 logical operators; the RAES exclusion uses
a positive empty-extraction comparison so the closed expression fits that
limit. A generic suffix list is not an acceptable substitute.

Static inputs are a separate authority. `GDC_ACCESS_SECRET_ID`, GDC/VM-Series
image import credentials, an optional VM-Series bootstrap XML template, and an
optional Vertex shared-key source remain named secrets in their owning project.
`portal/iam` must receive their full resource IDs from the existing
Terraform/bootstrap configuration surfaces and grant the provisioner named
read access there. Changing the dynamic-secret project must never redirect a
bare static reference or let the dynamic project admin grant stand in for
static-input access. In particular, the Vertex API project, the range compute
project, the shared-key source project, and the dynamic-secret storage project
are distinct concepts even when some IDs happen to be equal.

These static inputs must not be inserted into `runtime_secret_ids`, whose
current matrix intentionally grants shared platform-image readers. Keep one
separate, closed `provisioner_static_secret_refs` map keyed by the supported
runtime reference names and derive the deduplicated IAM set from its full
resource-name values. The Terraform output from that same map produces the
runtime references. Every
static secret, including a pre-existing or externally owned one, must exist
before workload IAM is applied and must use the existing per-secret binding
addressed by its full resource ID. A missing external secret fails deployment;
it never authorizes a project-level fallback. Do not independently transcribe
the same IDs into runtime env and IAM maps.

The repo-native IAM checker must be extended, not duplicated. It must
distinguish the platform project from the dedicated project, inspect custom
role permission lists across every permission namespace, parse the exact inputs
and composition of every IAM condition local, and admit only the exact
create-only binding plus the prefix-conditioned lifecycle/read bindings above.
Filtering a custom role to `secretmanager.*` before comparison is insufficient:
any extra IAM, storage, or future permission must fail the exact-role check.
Merely finding the expected local names is not sufficient. It must continue to
reject equivalent broad roles, renamed
Terraform resources, binding/policy forms, missing or widened conditions, and
dynamic-project bindings pointed at the platform project. After legacy drain,
remove the two expiring #1586 entries from `ALLOWLIST`; do not replace them with
a permanent exemption.

## Canonical configuration and runtime path

There is one operator-controlled seam: `dynamic_secret_project_id`. It belongs
in the closed `GcpBackendSettings` model and reuses
`_GCP_PROJECT_ID_PATTERN`; it is not a new provider DTO or free-form overlay.
The existing `shifter-config render` bridge publishes it as a typed Terraform
variable. Terraform passes it through the environment root and `platform-core`,
publishes the effective value as `dynamic_secret_project_id`, and
`scripts/gcp/render_runtime_env.py` emits it as
`GCP_DYNAMIC_SECRET_PROJECT_ID`.

The value is required in the closed GCP settings model. For the compatibility
release an operator explicitly sets it equal to `project_id`, so a deployment
can upgrade before the new project exists without hiding the migration posture
behind an omitted-value fallback. Once the legacy inventory is drained,
deployed GCP configuration must use a non-empty value distinct from the
platform project; do not add a permanent boolean that makes the insecure
posture look like a supported mode.

`GCP_DYNAMIC_SECRET_PROJECT_ID` is a non-secret resource identifier. It may be
a literal ConfigMap/Job env value, but it must travel through every existing
closed inventory and admission gate:

| Layer | Canonical incumbent and required behavior |
| --- | --- |
| Operator validation | `shifter/installation/settings_gcp.py`, the GCP example/tests, and the generated backend-bundle contract. Reuse the published project-ID grammar and contract migration workflow; never hand-edit generated JSON. |
| Terraform bridge | `shifter/installation/render.py`, `scripts/bootstrap/gcp_control_plane.py`, `platform/terraform/gcp/environments/gcp-dev`, and `modules/platform-core`. Derive one value from validated config; do not add a second tfvars script or static runtime override. |
| Project/API and IAM | `modules/project-services` enables Secret Manager in the supplied project; `portal/iam` remains the sole workload identity/resource matrix. Static secret owners continue to provide full IDs. |
| Runtime rendering | `scripts/gcp/render_runtime_env.py` consumes the Terraform output. Update the exact-key sets in `runtime_inventory_gcp.py` and their renderer/bundle/publication tests. No secret payload enters this output. |
| Platform settings | `shifter/shifter_platform/config/_cloud.py` owns the literal `os.environ.get` setting and export. Regenerate `config/env-manifest.json` through its existing command; do not hand-maintain a second settings reader. |
| Job projection | `engine/ecs/_env.py` forwards the key from the `platform-runtime` ConfigMap. It must not fabricate a different fallback: admission requires the Job literal to equal the ConfigMap value. Preserve the runtime-inventory/forwarding parity test. |
| Kubernetes admission | `shared/cloud/sensitive_env.py` correctly classifies an `_ID` as a non-secret pointer. Add the key to the chart and checked-in GCP `allowedLiteralEnv` surfaces, keep both renders in sync, and update the chart contract digest through the established workflow. |
| Provisioner resolution | Add the dynamic-project resolver beside `cloud/gcp/base.py:get_project_id`; all dynamic writers use it. Keep `get_project_id` for compute, Pub/Sub, static-secret defaults, and other platform-project operations. |

## Dynamic-secret code boundary

Every creator, reader/reconciler, and deleter below is in scope. Fixing only the
four files named in the issue would omit VPN secrets and leave teardown unsafe.

| Family | Current incumbent | Boundary requirement |
| --- | --- | --- |
| GCE and RAES guest/account/directory credentials | `gcp_guest_secrets.py` and `gcp_range_cell_outputs.py` | Create new names in the dynamic project; continue returning and persisting full `projects/.../secrets/...` references. Reconcile legacy names before minting replacement credentials. |
| GDC VM Runtime guest credentials | `_gdc_vm_secrets.py` and `_gdc_vm_naming.py` | Separate dynamic guest writes from `_read_secret_payload`, which reads static operator/image inputs. |
| GDC VM-Series SSH credentials | `gdc_vmseries_assets.py` and `gdc_vmseries_common.py` | Use the dynamic project for the SSH secret only. Continue deleting by the persisted full reference; GCS image and bootstrap-template reads remain in their configured projects. |
| Range Vertex credential | `gcp_range_vertex_creds.py`, `gcp_range_cell_credentials.py`, and `plans/_polaris_scripts_gcp.py` | Split Vertex/IAM, shared-key source, compute-host, and secret-storage project parameters. Pass the secret project or full reference into the guest script; it must not derive storage from the metadata-server compute project. |
| OpenVPN generation material | `vpn_secrets.py` and RAES activation/cleanup callers | Create issuer, server, and profile secrets in the dynamic project, preserve generation-bound full references, and retain per-secret gateway access. Legacy cleanup must not recompute only the newly configured project. |

The persistence contracts already support cross-project references. Reuse
`shared/range_cells.py`, `shared/remote_access.py`, the existing
`Range.provisioned_instances`/VPN binding fields, and
`engine/services/_operation_apply_raes.py`; they persist provider-native
references, not values. Do not add project fields to scenario DTOs, operation
envelopes, or secret payload schemas. Where a full reference is already
persisted, it is authoritative. RAES destroy paths are an exception to notice:
`raes_gcp_destroy.py` reconstructs deterministic secret names, so it needs the
bounded legacy-project lookup/delete behavior even though newer result paths
carry full references.

`vpn_secrets.GCPVpnSecretOps` currently uses one `project_id` both for Secret
Manager storage and for constructing the gateway service-account identity.
Those are separate concepts: moving storage must not point gateway identity
lookup at the dedicated secret project. Preserve the existing platform/range
identity source and pass or resolve secret storage independently. Apply the
same rule to the Vertex API project, shared-key source project, and compute
metadata project; equal strings in one deployment do not make them one field.

An existing secret is not proof that its lifecycle step completed. Reconcile
must converge the payload/version, the per-secret host or gateway IAM binding,
and persistence of the full reference independently. In particular,
`ensure_range_vertex_key` currently returns as soon as it can read a version and
can skip repairing a failed host binding, while the guest `AlreadyExists` path
must not publish a competing credential while another writer may still be
between container creation and first-version publication. Tests must cover an
empty secret left after create, a version added before IAM attachment, IAM
attached before result persistence, and retry/concurrency at each boundary.
Recovery reuses the existing credential whenever a version exists. If the
bounded wait still finds an empty container, the provisioner fails closed; the
operator first proves no creator is active, deletes that exact empty container,
and retries. It must never overwrite unrelated IAM bindings on a migrated
secret.

## Migration invariants

Migration is an expand, cut over, drain, and contract sequence with no secret
copy or live credential rotation:

1. **Expand:** publish the validated project seam, canonical new-name helper,
   full-reference handling, and dual-project legacy lookup/delete while the
   operator explicitly sets the dynamic-secret project equal to the platform
   project. An omitted value fails closed. While the two project IDs are equal,
   writers continue using their existing legacy grammar;
   canonical-prefixed secrets must not be created in the platform project.
   Existing IAM residuals remain during this compatibility interval.
2. **Cut over:** bootstrap the per-deployment project, enable Secret Manager,
   apply the dedicated IAM graph, and set `dynamic_secret_project_id`. New
   secrets use canonical names in the dedicated project. For an existing
   range, each ensure/reconcile path checks its persisted full reference or the
   old deterministic name in the platform project before creating anything;
   finding a legacy secret returns that reference unchanged. A container in any
   exact read location, including a legacy location, that has no published
   version is treated as an in-flight writer: wait for its first version and
   fail closed after the bounded retry rather than minting a competing canonical
   credential. Every VPN generation secret uses that same publish-once helper;
   an existing published version is authoritative and a retry only reconciles
   the per-secret gateway grant.
3. **Drain:** inventory all legacy grammars, not only guest SSH/RDP. Existing
   ranges continue to read their stored cross-project references and destroy
   deletes from the referenced/legacy project. Cloud Audit Logs and
   fingerprinted operational counters establish that no live range still uses
   the platform project. Do not copy payloads merely to make the inventory look
   empty.
4. **Contract:** after zero live legacy references and zero legacy dynamic
   secrets, remove the platform-project portal accessor and provisioner admin,
   remove both guard allowlist entries and dual-project fallback, and make a
   distinct dedicated project mandatory for deployed GCP configuration.

A naive configuration flip is unsafe. Current guest, GDC, Vertex, and VPN
delete/reconcile paths commonly recompute `get_project_id()`. They would orphan
old secrets. Worse, an ensure path could mint a new SSH/Vertex credential that
was never installed on an already-running guest, causing access loss. The
legacy-first rule for an existing range is therefore a correctness and
availability requirement, not optional cleanup polish.

After cutover, failure to reach the dedicated project must fail new creation;
it must never fall back to creating in the platform project. The only fallback
is a bounded lookup/delete of an exact legacy name or persisted legacy
reference. Preserve the current `NotFound`/`AlreadyExists` idempotency behavior
for concurrent provisioner jobs. Before switching writers, deployment checks
must prove that the project exists, Secret Manager is enabled, IAM has
propagated, and create/add/access/delete works under the real Workload Identity;
quota or policy failure is a provisioning blocker, not a reason to weaken the
boundary.

## Security, errors, and observability

- **Authentication:** preserve one Workload Identity GSA per portal and
  provisioner KSA. Cross-project IAM names those existing GSAs. Never grant the
  GKE node GSA, a Google-managed service agent, or a participant-controlled host
  the application permissions.
- **Portal authorization:** preserve the ownership, READY/current-generation,
  declared participant-channel, and provider-reference gates in
  `engine/services/_terminal.py`, `engine/services/_vpn.py`,
  `gcp_range_cell_outputs.py`, and `shared/operation_result_members.py`. A
  request never supplies an arbitrary Secret Manager reference for the portal
  to dereference; IAM is a second boundary, not a replacement for those service
  checks.
- **Shape and policy gates:** Pydantic settings, Terraform variable validation,
  renderer exact-key inventories, generated env manifest, Helm values schema,
  provisioner env parity, `sensitive_env`, and validating admission policy must
  all accept the same identifier and reject drift. The Terraform checker and
  effective-permission oracle prove both allowed and denied projects/prefixes.
- **Secret handling and OS exposure:** Terraform, tfvars, ConfigMaps, Job specs,
  persisted range state, and logs carry IDs/references only. Payloads remain in
  Secret Manager and in bounded process memory or mode-restricted files. The
  Polaris guest script may pass project/secret IDs as `gcloud` arguments, but
  never the JSON key; retain the mode-600 temporary file and secure cleanup,
  and do not echo provider stderr containing topology or policy detail.
- **Exceptions and API envelope:** reuse provisioner
  `cloud.exceptions.CloudSecretsError`, platform
  `shared.cloud.exceptions.CloudSecretsError`, and the established
  `engine.secrets.SecretsError` facade. Do not add a boundary-specific
  exception hierarchy. Portal-facing failures pass through
  `shared.api.errors`/`shared.errors.classify_user_message` as fixed generic
  messages; Google exception text, IAM policy, and secret references must not
  enter the response. The existing SSH/RDP path currently attaches provider
  text and `shared/cloud/gcp/secrets.py` logs full resource names; code touched
  by this boundary must converge those paths on the already-redacted OpenVPN
  behavior.
- **Logging and audit:** reuse provisioner `log_redact.safe_log_fingerprint`
  and platform `shared.log_sanitize.safe_log_fingerprint` for secret references
  and deployment/range topology. Log operation class, project-boundary class,
  result, and request correlation where available, never payloads. Cloud Audit
  Logs remain the authoritative cloud access evidence; do not create a second
  application permission ledger. Under the
  [Secret Manager audit classification](https://cloud.google.com/secret-manager/docs/audit-logging),
  create/add/delete are Admin Activity, but payload access is Data Access, so
  the dedicated project must explicitly enable and retain the
  `secretmanager.googleapis.com` Data Read audit category with no
  workload-principal exemption. Budget that volume and restrict access to the
  log sink. Monitor Secret Manager quota and create/delete failure rates because
  the dedicated project is now an explicit range-provisioning availability
  dependency.

## Revocation, quota, and cost contract

Deleting a Secret Manager object is not by itself end-to-end credential
revocation. Rollout evidence must state the separately measurable windows:

- a fresh Secret Manager read fails after the delete or IAM change has taken
  effect, but [IAM policy changes are eventually consistent](https://cloud.google.com/iam/docs/access-change-propagation);
- each portal process may retain a successfully read payload for up to its
  configured `engine.secrets._SecretCache` TTL (300 seconds by default), so the
  cache window is part of the published read-revocation bound;
- an SSH/RDP/account credential already delivered to or installed on a guest
  remains usable until the guest lifecycle or credential rotation removes it;
- an OpenVPN profile already downloaded remains usable until its generation is
  revoked at the gateway, not merely until its profile secret is deleted; and
- deleting a legacy Vertex service-account key prevents new key use but does
  not turn separate keys on one service account into separate IAM principals
  or revoke already minted access tokens. Issue #681 remains authoritative for
  the broker, model authorization, and final removal of that key path.

The rollout documents must record a dated, deployment-sized capacity and cost
calculation, not copy a timeless constant into application code. At minimum it
includes the one extra GCP project per deployment; project/bootstrap quota and
organization/billing prerequisites; the current per-project Secret Manager
[payload and request quotas](https://cloud.google.com/secret-manager/quotas);
active versions per range and overlapping generation; portal/guest/provisioner
access volume; legacy Vertex service-account key capacity while that path
exists; and Cloud Audit Logs volume. The billable Secret Manager dimensions
must be checked against the current [pricing source](https://cloud.google.com/secret-manager/pricing),
including replication locations, active versions, and access operations.
Provisioning and portal-read SLOs must budget for Secret Manager/project
unavailability without adding a platform-project fallback.

`platform/terraform/gcp/README.md` owns the project prerequisite, IAM, current
quota/cost calculation, and privileged probe-cleanup procedure;
`platform/k8s/gcp/README.md` owns runtime/admission and workload-identity
observability; and `docs/dev/gcp-range-cell-deploy.md` owns expand/cutover/drain,
partial-migration recovery, rollback, and the measured revocation windows. Do
not create a fourth rollout source or leave these operational facts only in a
test fixture.

## Verification contract

The implementation is not complete without repository-wide evidence for:

- Terraform variable/module/output propagation, dedicated-project API enablement,
  exact custom-role permissions, required prefix conditions, and named static
  secret readers;
- effective permission allows in the dedicated project and explicit denies in
  the platform project, unrelated projects, non-participant-readable families,
  outside the deployment prefix for existing-resource operations, and for every
  other workload/host identity;
- deterministic, collision-safe canonical names plus read/delete compatibility
  for every legacy grammar, including proof that compatibility-mode creation
  retains legacy names until the configured project becomes distinct;
- existing-range reconcile and destroy without duplicate credentials, rotation,
  access loss, or orphaned secrets, including reconstructive RAES teardown;
- cross-project portal SSH/RDP/OpenVPN reads through the existing cache and
  provider-neutral errors;
- Vertex guest access using the explicit secret project while Vertex API calls
  continue using their own project;
- runtime renderer inventories, published backend contract, env manifest,
  GCP role parity, sensitivity classification, Job admission, checked-in/chart
  manifest parity, and chart render digest; and
- removal of exactly the two #1586 guard allowlist residuals after drain.

Extend `scripts/check_tf_gcp_iam_resource_scope` and its independent
effective-permission oracle for static source/plan coverage. That parser is not
live permission proof. A deployed-environment probe must authenticate as the
real provisioner, portal, assigned host/gateway, peer host/gateway, worker,
launcher, and node principals and call the Secret Manager API. It must prove:

- provisioner create plus canonical add/access/delete in the dedicated project,
  and create denial in the platform and an unrelated project;
- denial of provisioner add/access/delete/set-IAM-policy for an out-of-prefix
  dedicated-project secret (while explicitly recording that parent-scoped
  create inside that project cannot be a negative control);
- portal access only to each participant-readable class, with mutation,
  Vertex-key, VPN issuer/server, non-published bootstrap/directory, platform,
  and unrelated-project negatives;
- assigned host/gateway access only to its individual secret, with peer-secret
  and project-wide negatives; and
- no dynamic-secret access by workers, launcher, nodes, or other workload
  identities.

Use a run-unique probe namespace, bounded retries for documented IAM
propagation, and an independent bootstrap/operator cleanup identity for the
deliberate out-of-prefix empty resource. Payloads enter the probe over stdin or
a mode-restricted temporary file, never argv, Terraform, or captured output.
Record principal, permission, resource class, allow/deny result, correlation
ID, and elapsed propagation time, with resource names fingerprinted. Cleanup
must treat only an actual not-found response as idempotent success, aggregate
all other delete failures as payload-free fingerprinted evidence, and preserve
both the boundary and cleanup failures when they occur together. Exercise
project/API unavailability and failure between legacy discovery, new creation,
reference persistence, IAM attachment, and cleanup. Do not add a second static
range-secret checker or claim completeness from Terraform source substrings.

## Non-goals and anti-patterns

- No broker service or broker API in this change; no generic secret repository
  rewrite in anticipation of one.
- No project-per-range/workspace/user topology and no sharing across unrelated
  deployments.
- No relocation of static runtime/operator secrets, Terraform state, or GCS
  assets into the dynamic project.
- No change to workspace/organization authorization, scenario schemas, range
  DTOs, persistence models, secret payload formats, or the cache design. Its
  existing configured TTL remains part of the documented revocation window.
- No redesign of GKE/node IAM, GCS, Pub/Sub, Compute, Vertex authorization,
  service-account pools, or range-network boundaries.
- No secret values, service-account key JSON, or copied secret versions in
  Terraform state, tfvars, ConfigMaps, Job literals, argv, logs, or migration
  inventories.
- Do not overload `GCP_PROJECT_ID` or `GCP_RANGE_VERTEX_PROJECT_ID` with secret
  storage meaning; do not accept multiple independent sources for the effective
  dynamic project.
- Do not treat labels, a name prefix alone, or a reduced same-project custom
  role as a create boundary. Do not leave `roles/secretmanager.admin` in either
  project.
- Do not rename/copy live secrets on cutover, synthesize a replacement secret
  when a legacy credential exists, or remove legacy IAM before all live
  references and reconstructive deleters have drained.
- Do not make a Secret Manager outage or permission denial trigger same-project
  creation fallback.
- No implementation is part of this preflight.

## Delivery ownership

Issue #2083 owns the Terraform, runtime, migration, and live effective-permission
implementation of this contract. Issue #681 owns participant model budgets and
authorization. This design does not create a generic secrets platform or move
those implementation responsibilities into #1586.
