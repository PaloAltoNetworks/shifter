# GCP workload resource IAM preflight

Issue: GitHub #1517, "REV1 Security: scope GCP workload identities to named
resources."

## Decision

Keep workload identity and its cloud authorization policy in
`platform/terraform/gcp/modules/portal/iam`. Pass that module resource IDs from
the modules that already own the resources: `portal/secrets` owns runtime
Secret Manager resources and `portal/gcs` owns the assets and audit buckets.
Do not create a second secret inventory, bucket-name convention, IAM module, or
application-side authorization layer.

Project IAM remains appropriate for APIs whose Google roles are inherently
project scoped (for example Pub/Sub or Compute). It is not the authorization
surface for application secret payloads or objects. Bind
`roles/secretmanager.secretAccessor` on each named secret and bind storage
roles on each named bucket. Portal and provisioner self-`signBlob` grants stay
on their own service-account resources.

The workload/resource matrix is the contract. It must be expressed once in the
IAM module, using resource IDs received from the owning modules, and drive the
`for_each` bindings. Tests may state the expected sets as an independent oracle,
but production code and renderers must not maintain parallel allowlists.

## Required resource boundaries

The exact matrix must be derived from runtime use, not from the roles currently
granted:

| Identity | Secret Manager | Cloud Storage |
| --- | --- | --- |
| `portal` | Named runtime bundles actually hydrated at startup, plus read-only access to provisioner-created guest credentials whose references are consumed through `shared.cloud.get_secrets_store()` | The assets bucket only, with the object verbs needed by CMS/CTF upload, finalization, tagging, deletion, and signed URLs |
| `workers` | Named runtime bundles actually hydrated by the shared portal-image entrypoint | The assets bucket only; preserve only the read/write verbs exercised by worker commands |
| `ctf-scheduler` | Named runtime bundles actually hydrated by the shared portal-image entrypoint | None unless an effective-permission test demonstrates a scheduler storage call |
| `provisioner` | Named operator/bootstrap inputs it reads, plus lifecycle access only to its dynamic guest-credential namespace | The Terraform state bucket, assets bucket, and any explicitly configured Polaris/VM-Series bucket, each with only the verbs exercised there |

There is an important current constraint: `web`, the Django workers, and the CTF
scheduler all receive the shared `platform-runtime` ConfigMap, and
`shifter/shifter_platform/entrypoint.sh` eagerly fetches every present DB, app,
Guacamole, DC-domain, Redis, and optional email secret reference. IAM cannot be
narrower than that effective startup contract. Either preserve those named
reads and document them, or separately split the runtime-env/entrypoint binding;
do not remove IAM and leave workloads crash-looping. Splitting runtime env is a
separate defense-in-depth change, not a prerequisite for replacing project-wide
access with per-secret bindings.

The provisioner is different from a reader of pre-created secrets. Google
authorizes `secretmanager.secrets.create` on the parent project, before the new
secret exists; a `resource.name` condition cannot reliably constrain the
request's `secretId`. Therefore a same-project prefix condition is sufficient
for access/update/delete of existing dynamic secrets, but not for creation.
The secure lifecycle boundary is a dedicated range-secret project (preferred)
or a broker/service boundary that owns creation. A reduced custom role in the
platform project is not equivalent to name-scoped creation and must not be
described as such. The project/broker seam must be an explicit Terraform input
and runtime project setting so a later tenant- or deployment-specific secret
project does not require editing the canonical policy.

Until dynamic-secret creation moves behind that boundary, implementation must
not claim the provisioner lifecycle acceptance criterion is met merely because
read/delete permissions carry a prefix condition.

## Cross-cutting incumbents to reuse

- Resource ownership and outputs: `platform-core`, `portal/secrets`,
  `portal/gcs`, and their existing `runtime_secret_ids`,
  `assets_bucket_name`, and `terraform_state_bucket_name` outputs.
- Identity binding: `portal/iam` and its existing GSA-to-KSA Workload Identity
  members. Kubernetes service-account names remain owned by the Helm chart and
  `scripts/bootstrap/gcp_control_plane.py`.
- Runtime shape validation: `scripts/gcp/render_runtime_env.py` and its tests.
  It remains the fail-closed producer of non-secret config and secret
  references; raw payloads do not enter ConfigMaps or generated values.
- Secret hydration and schemas: `entrypoint.sh` / `entrypoint-lib.sh` remain the
  owners of DB/app/Redis/email bundle parsing. Do not reproduce their JSON
  schemas in Terraform or an IAM checker.
- Application cloud boundary: portal code continues through
  `shared.cloud.get_secrets_store()` and the existing storage protocols,
  `CloudSecretsError`, and `CloudStorageError`. Provisioner code continues
  through its existing `cloud` adapters and `safe_log_fingerprint` logging.
- Dynamic credential naming: reuse and converge the existing helpers in
  `gcp_guest_secrets.py`, `_gdc_vm_naming.py`,
  `gcp_range_vertex_creds.py`, and `gdc_vmseries_common.py`; IAM conditions must
  not invent a fifth, independently maintained prefix grammar.
- Guard workflow: follow the repo-native standalone `scripts/check_tf_*`
  checker + unittest + pre-commit + `_quality.yml` pattern. Checkov remains the
  broad IaC backstop, not the sole acceptance test for this repository-specific
  identity/resource relationship.

## Cross-cutting security layers

| Layer | Required behavior |
| --- | --- |
| Terraform input/output shape | Resource names and the optional dedicated secret project flow through typed module variables and existing outputs. Validate non-empty project/resource identifiers and reject a configured dynamic-secret project that is inconsistent with the runtime project used by provisioner secret clients. |
| IAM policy gate | No application GSA may receive project-level `roles/secretmanager.secretAccessor`, `roles/secretmanager.admin`, or `roles/storage.objectAdmin`. The guard must also inspect project-level custom roles used by these identities for equivalent secret payload/lifecycle or object mutation permissions. Legitimate CI/bootstrap and range-host identities are different principals and must be distinguished, not globally banned by role string. |
| Workload Identity/auth | Preserve one GSA per `portal`, `workers`, `ctf-scheduler`, and `provisioner`, the existing KSA namespaces, and self-scoped `signBlob`. Do not move data permissions to the GKE node GSA or broaden KSA membership. |
| Secret handling | Config and Terraform/Helm artifacts contain references only. Payloads continue through Secret Manager and stdin-based entrypoint parsing. Per-secret IAM is authorization; it is not a new secret schema, cache, or synchronization mechanism. |
| Env/config binding | Reconcile the IAM matrix against `render_runtime_env.py`, the shared ConfigMap, `entrypoint.sh`, and `_GCP_PROVISIONER_ENV_KEYS`. Optional secret/bucket inputs must add/remove matching bindings deterministically. |
| OS/process exposure | No secret values, service-account keys, signed URLs, or rendered Terraform outputs in argv, shell history, plan comments, or process listings. Preserve stdin/file-descriptor patterns and short-lived Workload Identity credentials. Resource IDs are configuration, but provisioner logs should retain fingerprinting where IDs reveal tenant/range topology. |
| Error envelope and logs | Continue using provider-neutral cloud exceptions. User/API responses must not include Google SDK errors, IAM policies, signed URLs, secret names, or payloads. Operational logs may identify the workload and permission class; dynamic resource references use `safe_log_fingerprint`, never payloads. |
| Persistence/audit | Terraform state necessarily records IAM resources and resource names, never secret payloads beyond existing seeded-secret debt. GCS audit logs and Cloud Audit Logs are evidence sources; do not add a second application permission ledger. |

## Verification guardrails

The repository-specific Terraform guard must fail closed for all
`google_project_iam_member`, `google_project_iam_binding`, and authoritative
`google_project_iam_policy` shapes that attach the forbidden predefined roles
to an application workload identity. It must cover direct literals and the
current `for_each`/local-map construction, and its negative fixtures must prove
that renaming the Terraform resource does not bypass detection. Custom roles
attached at project scope require permission inspection, not a role-name
allowlist. Every exception needs the existing ADR exception process, owner, and
expiry; inline comments are not bypasses.

Effective-permission tests must enumerate, for each of the four workload GSAs:

- project roles retained;
- exact named secrets readable;
- dynamic-secret namespace/project and lifecycle verbs;
- exact buckets and object verbs;
- self-scoped service-account permissions; and
- explicit denied examples outside each set.

Assert the rendered/planned IAM graph, not only source substrings. Include
optional email and external bucket cases so the obvious next resource can be
added through a map/input rather than by copying a Terraform resource block.

## Non-goals and anti-patterns

- No changes to application authorization, Django DTOs/models, database
  repositories, secret payload schemas, or API error schemas.
- No redesign of Pub/Sub, Compute, Artifact Registry, GKE RBAC, node IAM,
  Terraform backend bootstrap, GCS encryption, or range-host identities.
- Do not grant resource permissions to the node GSA, a Google-managed service
  agent, `allUsers`, or `allAuthenticatedUsers` to make a workload pass.
- Do not replace one broad predefined role with an equally broad custom role,
  or treat OAuth `cloud-platform` scope as IAM authorization.
- Do not use bucket object-name conditions where a bucket-level binding already
  expresses the real boundary; add an object prefix only when the application
  contract and tests genuinely isolate that prefix.
- Do not hard-code environment bucket names or secret IDs in IAM, duplicate the
  `runtime_secrets` map, or derive resource names by string surgery when an
  owning-module output exists.
- Do not use one IAM condition over inconsistent dynamic-secret naming helpers.
  Converge the naming contract or use the dedicated-project boundary.
- Do not weaken Checkov, TFLint, Terraform validation, ADR guard, or deployment
  workflow gates. A narrow scoped exception is preferable to an unreviewed
  global skip, but this issue should require no exception for application data
  access.
