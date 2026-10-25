# GCP native identity implementation

The shared `shared.gcp_native_identity` contract validates Terraform readback:
explicit native mode, exact instance/project, complete distinct workload users
and the documented GSA-to-PostgreSQL normalization. Installation settings are
closed; `render_runtime_env`, bootstrap Helm values and the GCP chart projection
consume the same validated metadata. Password mode remains the default.

`DB_AUTH_MODE=cloud-sql-proxy` requires GCP, local `127.0.0.1:5432`, the attached
native SQL login and no password/RDS selector. Stock Django PostgreSQL and
psycopg connect locally with an empty password. The entrypoint still hydrates
application secrets independently and keeps runtime migration execution off.
The separate deployment owner retains password SQL ownership through the native
connector transport. Guacamole keeps its isolated password duty and obtains
connector transport only; guacd has neither SQL nor cloud authority.

## Native permission and process boundaries

| Duty | Authority and justification |
| --- | --- |
| Application/policy SQL client | `roles/cloudsql.client` for connector connection and `roles/cloudsql.instanceUser` for IAM login, conditioned on the exact installation instance. [Native login contract](https://docs.cloud.google.com/sql/docs/postgres/iam-logins). |
| Guacamole client/deployment owner | Instance-conditioned connector role only; their separate password/database duties persist. [GKE connection pattern](https://docs.cloud.google.com/sql/docs/postgres/connect-kubernetes-engine). |
| Portal directory recheck | Custom role containing only `firebaseauth.users.get`; no hash export, directory mutation or configuration access. [Native API permission map](https://docs.cloud.google.com/identity-platform/docs/access-control). |
| Dynamic-secret provisioner | Create-only parent role plus canonical prefix-conditioned existing-secret lifecycle; portal reads only classified participant-access names. Static secrets retain named bindings. |
| Operator | Existing deliberately assigned cloud/CI powers are additive. Application authority requires its own explicit principal/policy grant and admitted credential ceiling. |

The official Auth Proxy v2.18.3 is pinned by OCI index digest. It uses private
IP, automatic IAM login, loopback SQL, its startup health check and attached
Workload Identity. A Kubernetes native sidecar starts before the application and
terminates with Jobs. It runs as UID/GID 65532 with read-only filesystem, no
privilege escalation, dropped capabilities, RuntimeDefault seccomp and bounded
resources. No command, credential, mount or impersonation override is accepted.
Admission compares the exact profile against trusted runtime parameters, and
deterministic recovery rejects proxy substitutions. Kubernetes 1.31 is the
supported native-sidecar baseline. API/metadata lanes retain existing scopes;
new SQL egress names only the instance address on TCP 3307, never guests/plugins.

`reconcile_gcp_database_duties` uses actual owner SQL authority. It removes
documented provider runtime role defaults, checks effective inherited ownership
and privileges, grants existing application duties to native logins and denies
policy identities application database access. The provisioner retains its
function-bound duty. Unknown privilege drift aborts instead of being silently
accepted. It does not weaken the migration owner or use global REASSIGN OWNED.

## Policy separation and orchestration

The released OpenFGA server has two private TLS/PSK listeners with separate
KSAs/GSAs, credentials and database logins. PostgreSQL grants give runtime
read access to stores/models/assertions/version and tuple/changelog mutation;
administration gets object mutation; only the policy migration duty owns the
schema and migration version. PUBLIC/default grants and effective role
inheritance are checked. Runtime administrative methods fail in the actual
released server because its SQL role lacks the required write privileges.
Runtime tuples remain a trusted-client capability.

Chart-owned SQL and policy resources are projected into the staged GCP workflow;
bootstrap uses the same Helm/native/migration projections. Policy credential
sync fetches three named provider bundles, validates separation before writes,
and applies only named Kubernetes Secrets plus the public CA ConfigMap. Helm
values and generated manifests contain references/public connection metadata.
Bootstrap's temporary migration lane includes exact SQL, Google private/restricted
VIPs, GKE metadata and namespace/pod-selected DNS before Helm installs the platform
policies. The optional model-access control workload receives the same native
workers duty in both deployment paths. The publisher maps its runtime token to
the established chart key, preserving the existing mount contract. Migration
prerequisites survive hook completion. Fresh store/model publication
is deployment administration; blank IDs leave the portal client unbound.

## Verification

Terraform mock tests verify users, exact instance roles and absent runtime
password-secret reads. IAM negative tests reject widened conditions, directory
permissions/identity and login type. Rendered CEL tests reject sidecar and
credential substitutions while accepting the canonical Job. Native SQL settings,
entrypoint subprocess, driver boundaries, Helm/Kustomize/bootstrap parity and
named-secret subprocess tests cover runtime wiring.

The pinned OpenFGA/PostgreSQL harness proves runtime administrative denial,
distinct admin success, inherited-role rejection, real native SQL duties and
existing-datastore owner upgrade. Its cold database deliberately uses a custom
name. These local results do not prove GCP credential renewal, Cloud SQL owner
grant behavior or actual deployment IAM/network isolation. Follow the
[operator acceptance guide](../../ops/gcp-native-identity.md) during the
installation's live qualification session. No S8 authority activation is implied.

Native driver tests require an empty password and reject stored password input.
The provider/Kubernetes CLI adapters validate named references and execute fixed
argv without a shell. Scanner annotations cover those specific empty-value and
native-CLI cases. Fixed Google API/metadata addresses identify documented
provider endpoints; egress tests reject arbitrary destinations.
