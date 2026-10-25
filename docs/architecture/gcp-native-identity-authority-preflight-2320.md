# GCP native identity and operator authority preflight (#2320)

Status: S7 source integration authorized. This preflight records the assessed
baseline; the approved implementation and SQL-enforced administration split are
recorded in [the final design](../design/gcp-native-identity-integration-2320.md).
Source delivery does not claim live deployment qualification. Application
authority cutover remains S8.

Contract: the supplied #2320 issue, ADR-066, and the
[#2314](account-principal-scope-preflight-2314.md),
[#2315](openfga-authorization-preflight-2315.md), and
[#2316](unified-credential-auth-preflight-2316.md) boundaries. No formal
requirement accompanies this run. This note records constraints and unresolved
deployment choices, not an implementation plan or live qualification.

## Authority and topology decisions

Preserve deliberately assigned project-admin authority for deploy, destroy, and
operator automation. The same service may have full application authority as a
second explicit grant, bounded by its admitted credential ceiling. Cloud IAM,
OpenFGA policy, Identity Platform directory permissions, SQL duties, Kubernetes
RBAC, and CTF participation are different authorities. Project number, project
ID, Identity Platform tenant, and application Account are different identities.
Neither deployment access nor directory administration creates an application
grant; service-account email is not the immutable provider subject.

Reuse the existing purpose identities and KSA/GSA bindings. Broad power is an
intentional operator assignment, never a new workload default. Protect the
identity's use rather than silently reducing the operator's powers. Evaluate
effective organization/folder/project/resource grants, group membership,
conditions and deny policies, impersonation chains, and workload creation or
modification rights. Inspect both token minting and `actAs`: attaching a powerful
identity to attacker-controlled execution is credential exposure even without a
token-creator grant. Preserve resource-scoped self-signing and named-resource
bindings where already required. Document each changed permission against the
actual native API operation and target resource. Use additive Terraform IAM
members unless the module deliberately owns the complete policy; an
authoritative replacement must not erase unrelated chosen operator grants.

The incumbent GKE binding names a project-wide pool plus namespace/KSA, not a
cluster. Inventory other clusters that can create the same tuple; cluster
separation alone does not isolate that identity. Preserve rejection of host
network/host-path exposure and keep node credentials separate from workload
credentials. These are documented [GKE identity and metadata limits](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/workload-identity).

S7 supports one project and one shared Cloud SQL instance; accounts need no
dedicated project/database. The earlier ADR-008-R7 requirement for a distinct
dynamic-secret project is superseded for this slice by the operator's explicit
topology choice. Keep `dynamic_secret_project_id` explicit, including when equal
to `project_id`; a distinct deployment-owned project remains supported. In one
project, create-only permission can create arbitrary empty Secret containers:
it is **not** a name-prefix restriction or separate incident/quota boundary.
Existing-secret lifecycle remains prefix-conditioned; static policy/operator
secrets use exact named bindings; guests retain only their intended capabilities.
Do not broaden payload access to solve creation. Current checker logic and
settings descriptions still express the earlier migration-only posture; S7
must reconcile those incumbents with both supported topologies and negative
permission evidence, without disabling checks or adding blanket exemptions.

## Native credential and datastore arrangement

Build on `shifter/shifter_client.ServiceClient.from_adc` and the
[supported credential contract](../technical/shifter_platform/access-credentials.md).
Keep Google application ID tokens and cloud OAuth access tokens on separate
transports; Firebase human proof and OpenFGA preshared credentials remain
separate again. Attached GKE identity must resolve to the registered Google
service-account numeric subject. Direct federated KSA identity is not that
subject; use the established exact KSA-to-GSA impersonation binding. Local and
external ADC require the supported explicit target where needed. Renewal must
include the source proof supplier, not merely the final token: a one-time token
file or CLI export cannot sustain a long-running client. Never accept arbitrary
ADC URLs/executable suppliers, static keys, or a caller-supplied bearer callback.

Cloud SQL connection authorization, IAM database login, and PostgreSQL grants
are three gates. Use supported native automatic IAM authentication where the
selected released connector and actual driver/runtime support it. Bind private
instance connection identity, IAM database username, and connector identity
consistently; preserve migration-owner, portal runtime, function-bound
provisioner, Guacamole, and dedicated OpenFGA duties. The OpenFGA database may
share the instance but has its own database and runtime/migration grants;
Django and provisioner identities cannot query its tables. Check inherited SQL
roles, `PUBLIC`, default privileges, ownership and function execution, not only
login success. A Google service-account PostgreSQL username uses the provider's
documented normalization, not the application principal UUID.

Repository gaps constrain the choice:

- `config._database_settings` interprets `DB_IAM_AUTH` as RDS IAM and
  `entrypoint.sh` enables it only for AWS. Turning it on for GCP is incorrect.
  The GCP Terraform database module currently provisions password users without
  the IAM-authentication flag; named secret bundles still hydrate passwords.
- The provisioner's `provisioner_db.get_db_connection` and `cloud.gcp.db_auth`
  already mint native proof on new IAM connections, but do not provide an
  automatic connector. Reuse their boundary, not raw exception logging/text or
  an assumption that encrypted direct TCP verifies server identity.
- Provisioner admission allows one container, no init containers, and only its
  canonical volumes/environment. A proxy sidecar or socket mount fails that
  policy. Select a supported driver-level arrangement there, or reconcile the
  admission contract explicitly under the parent source gate. No new launcher
  or credential broker is justified. For Django and the released Go OpenFGA
  binary, verify the connector/proxy integration each actually accepts.
- Native connectors need their API/metadata and private-instance egress lanes;
  the current generated database policy permits direct PostgreSQL on 5432,
  whereas connector traffic uses 3307. A local proxy listener belongs on
  loopback or a protected Unix socket, with startup readiness and clean Job
  shutdown; do not expose it through a Service or node/guest interface.
  Account for DNS, verification-key retrieval and the actual credential mode's
  Google API/STS/IAM Credentials dependencies without blanket guest/plugin
  internet or metadata access.

The actual supported released driver/connector/process arrangement and its
renewal behavior must be established before claiming acceptance. A native
library unit test, existing live SQL connection, or successful first login is
insufficient evidence of reconnection after expiry. See
[Cloud SQL IAM authentication](https://docs.cloud.google.com/sql/docs/postgres/iam-authentication),
[native login/network requirements](https://docs.cloud.google.com/sql/docs/postgres/iam-logins),
and the [official Python connector's driver surface](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector).

## OpenFGA and directory limits

Retain S2's pinned server/SDK/model, private ClusterIP, verified native TLS,
preshared authentication, disabled Playground/profiler, loopback-only unused
gRPC, bounded pools/resources, readiness and metrics. Deploy datastore
migrations before rollout; store/model publication and assertions remain
deployment administration. Keep hook/job prerequisites alive through completion
and qualify initial enablement as well as upgrade. Use the released chart's
contract in GCP Kustomize and bootstrap Helm, including explicit admin-job
ingress and egress; the current chart admits portal ingress only.

**Preshared keys do not assign per-client HTTP privileges.** The approved
integration separates private runtime and administration listeners and gives
them different PostgreSQL duties. The runtime login has no store/model/assertion
mutation authority; released-server tests prove those operations fail without
changing data. Administration has its own native workload identity, key, TLS key
and private ingress. Runtime tuple writes remain a trusted-client capability,
so application credential ceilings and domain authorization are still required.
No experimental access control or custom proxy is used.

Reuse `config.identity_platform`'s Firebase Admin initialization/ADC and
tenant-aware provider state, `VerifiedIdentity`, and management's immutable
binding/lifecycle facade. Terraform now assigns only `firebaseauth.users.get` through the portal's
custom role for native lifecycle/revocation rechecks; directory writes need the exact supported native operation permissions, not an
unexamined project-admin or service-agent role. User read/create/update/delete
and email operations differ; do not grant password-hash export or provider
configuration-secret access incidentally. Provider project/tenant must agree
across Terraform, browser, verifier and lifecycle recheck. Native directory
effects do not replace local binding collision, disable, revocation, strict
audit or durable ambiguous-effect handling, and never run under a SQL lock.
No second directory workflow, user schema or exception hierarchy is needed.
See [Identity Platform's API permission map](https://docs.cloud.google.com/identity-platform/docs/access-control).

## Canonical incumbents and layers every binding passes

Paths below `config`, `shared`, `management`, `workspaces`, and `engine` in this
table are relative to `shifter/shifter_platform` unless otherwise stated.

| Layer | Incumbent and required conformance |
| --- | --- |
| Federation and cloud IAM | `platform/terraform/gcp/modules/cicd-oidc-identity/{main,inventory}.tf`, global `cicd-oidc` roots, `scripts/bootstrap/gcp_foundation.py` and `gcp_runner.py`. Retain immutable repository/owner IDs, exact Environment/ref/workflow/reusable-workflow tuples, disjoint purpose subjects and exact GSA bindings. Verify effective trust and inherited IAM, not just Terraform text. Google `actAs`, access/ID-token minting and self-signing remain distinct permissions. |
| Identity, transport and policy shapes | `config.service_identity`, `identity_platform`, `_credential_settings`, `_drf_settings`; `shared.verified_identity`, `identity_scope`, `credentials`, `authorization`; `management.services`; `workspaces.services`. Exact issuer/audience/tenant/subject and live lifecycle precede ceiling plus policy plus domain checks. Preserve bearer-first failure, session CSRF, `StrictJSONParser`/`ClosedSerializer`, opaque denial and no new DTO, scope or role evaluator. S7 configuration does not activate S8. |
| Installation and generated configuration | `shifter/installation/{schema,settings_gcp,bundle_gcp,render,runtime_inventory_gcp}.py`, published backend contract, `config._env_manifest`/`env-manifest.json` and bounded settings. Closed operator intent and secret references enter once; Terraform outputs feed `scripts/gcp/render_runtime_env.py`, `render_overlay_identity.py`, `render_private_service_netpol.py` and `scripts/bootstrap/gcp_control_plane.py`. Keep aliases/schema constraints, manifest generation, process-role inventory and renderer parity synchronized; do not hand-edit generated overlays. OpenFGA URL/ULIDs/100–10000 ms deadline and bounded token file use `OpenFgaRuntimeSettings`. HTTPS syntax alone does not prove private routing. |
| Secrets and OS/process | `portal/secrets` outputs and `portal/iam/main.tf`'s canonical resource matrices, startup hydration, `shared.cloud.sensitive_env`, Kubernetes `_secrets` and `_job_manifest`. Adding an OpenFGA secret to `runtime_secret_ids` currently fans read access out to portal, workers, scheduler and launcher: introduce no such accidental grant. Split intended readers in the existing matrix. Values use named Secret/file bindings with correct non-root readability; `_FILE`/`_URL` are reference classifications, so never embed credentials in them. Keep tokens/URIs/keys out of argv, URLs, shell tracing/history, diagnostics, ConfigMaps, public artifacts and Terraform outputs; `sensitive` does not remove values from state. Mounted rotation does not reload the already-created OpenFGA client automatically; qualify restart/reload and overlapping-key/CA rotation through the supported lifecycle. |
| Kubernetes, network and guest host | `platform/k8s/gcp/base/{serviceaccounts,rbac-job-launcher,validatingadmissionpolicy-provisioner-jobs,networkpolicies,runtime-plugins}.yaml`, GKE node pools, `shared.cloud.kubernetes`, GCP task profile, `engine.ecs` forwarding and chart counterparts. Preserve admission/environment parity, non-root/read-only/seccomp posture, restricted Job launch, gVisor plugin isolation, dedicated nodes and guest/metadata separation. No operator/policy credentials in plugin input, guest metadata, images or shared volumes. Check token-request, impersonate, bind/escalate, exec, workload/SA/ConfigMap mutation and secret-mount permissions; absence of Secret `get` alone proves little. NetworkPolicy allows are additive: evaluate broad existing policies and namespace/pod selectors together, metadata/DNS and translated Dataplane V2 endpoints included. |
| SQL and external effects | `config._database_settings`, domain forward migrations, `shifter/engine/provisioner/{provisioner_db,cloud/gcp/db_auth}.py`, operation-input/result append boundary, Engine migration `0083_reconcile_subnet_coordination_grants`, and workspaces authorization journal/fences. Bind native login identities to existing narrow duty roles; do not copy the hardcoded `provisioner_runtime` grant assumption to a new IAM login. Preserve database constraints, durable request digests, store/model binding, unresolved outcomes and primary readback; no credential persistence, tuple mirror, generic transaction framework or network I/O inside transactions. |
| Errors, audit and observability | `shared.api.errors`, owning cloud/identity exceptions, `shared.audit`/`audit_adapter`, `shared.log_sanitize`, `config._logging_config`/`health_checks`, and provisioner `log_redact`/ECS logging. Normalize provider failures to bounded internal reasons and the existing request-ID envelope. Do not propagate raw SDK exception text, chained tracebacks, credentials, claims or SQL URLs; string sanitization is not secret redaction. Strict security-mutation audit, coarse health and low-cardinality renewal/policy/database failure metrics remain canonical. Cloud Data Access logs supplement application audit and need explicit coverage/retention without leaking payloads. |

Secret-backed environment injection protects manifest values, not access by the
same process identity or privileged node operators. Limit process/filesystem
access and exclude environment dumps and crash diagnostics from retained
evidence. Mounted `_FILE` references must be real readable files in every
consumer; declaring a path in a ConfigMap does not deliver the secret.

## Evidence, extension seam and boundaries

Acceptance evidence must pair intended operator successes with denied unrelated
workload, guest and plugin paths: federation substitution; GSA impersonation or
attachment; named secret access; policy TLS/auth/ingress; datastore login and
cross-duty grants. Use synthetic fixtures and incumbent
`scripts/check_tf_gcp_{wif_trust,iam_resource_scope,runner_network}`,
`scripts/gcp/probe_range_secret_permissions.py`, IAM drift workflow, renderer
tests, task-runner/admission parity tests, native client tests, real PostgreSQL
and the released OpenFGA harness. Live qualification must use the actual
identities/network/runtime, including new connections and both cloud/app
requests beyond credential expiry, unavailable renewal, and disabled admission.
Retain bounded redacted results; static lint cannot prove live denial or renewal.

The extension seam is the existing closed GCP installation/runtime bundle and
purpose/workload maps: explicit GSA target/grant resource, renewable ADC mode,
application audience, provider project/tenant, database connection identity/auth
mode/duty, and OpenFGA endpoint/store/model/CA/credential references and bounds.
Only genuine operator intent belongs in settings; provider payloads and derived
IDs remain generated outputs. One future operator identity, deployment hostname
or optional second project must vary those parameters without changing principal,
scope, action, directory, policy or Job workflow contracts. Do not introduce a
generic IAM policy language, new auth backend or per-customer deployment fork.

Required delivery gates remain ADR guard at CI level, TFLint and relevant
Terraform/checker tests, actionlint for workflows, kube-linter/kubeconform and
rendered manifest/admission checks, import/layer checks for Python boundaries,
and the PostgreSQL/released OpenFGA lanes when relevant. Publish schema/runtime
inventory changes through the established contract generation checks. No skipped
negative test, weakened rule, or undocumented scanner suppression qualifies.

Non-goals: implementing this issue during preflight; approving custom source;
S8 activation or legacy authority migration; AWS delivery (#2313); a new token
format, credential broker, directory/policy evaluator, proxy protocol or renewal
daemon; mandatory per-customer projects/databases, mesh, Vault or second approver;
rebuilding plugin/guest isolation; cloud permissions managed by tenant pack code;
and claims of customer infrastructure isolation from application Account scope.
