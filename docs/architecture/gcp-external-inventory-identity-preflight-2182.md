# GCP identity and bootstrap from external inventory (#2182)

## Approved scope amendment: one project

The operator explicitly selected one project per deployment during #2182 to keep
setup practical for nonprofits, academics and university IT teams. Optional
two-project isolation is deferred to [#2189](https://github.com/Brad-Edwards/shifter/issues/2189).
This amendment supersedes the stronger administrator-isolation requirements in
the original preflight below. It does not relax exact repository, purpose,
Environment, workflow, numeric-identity, provenance or Checkov checks.

Application resources, runner and automation identities use the single
`installation.settings.project_id`. Deploy/destroy retain the existing project
IAM and service-account administration capabilities required by platform
Terraform. They are trusted administrative jobs and can rewrite project access;
the implementation makes no containment claim against those jobs. Separate state
buckets scope direct grants and ownership, but do not defeat project IAM admin.
Migration preserves the existing project and resource names without a mandatory
project split. See the updated [contract](deployment-inventory-contract.md) and
[operator guide](../dev/gcp-inventory-bootstrap.md) for the supported behavior.

## Original preflight assessment


Status: pre-implementation guidance. Issue #2182 is the shipping contract;
#2178 owns the common external deployment contract. Requirement: PLAT-005,
Per-Deployment Configuration. This note refines ADR-011 and ADR-004-R23, without implementing a
schema, renderer, workflow, identity, or live cutover.

## Boundary and contract ownership

At this preflight, the working tree contains uncommitted `deployment_inventory*`,
`deployment_identity_gcp.py`, `scripts/bootstrap/inventory_*.py` and Terraform/WIF
changes. These are draft consumers/contracts, not evidence that #2178's common
contract has been adopted or the acceptance criteria met. The existing
`shifter/installation` contract remains the incumbent for installation intent.
Settle common contract/version ownership with #2178 before shipping its GCP consumer;
do not ship a provisional GCP-only inventory schema or secret-reference syntax.
This note specifies semantic obligations, not new field names or a work plan.

The private deployment repository owns deployment records and approved changes
to them. Product code owns common tooling, purpose capabilities, and validators.
The GCP consumer accepts the common loader's validated record and emits bounded
GCP Terraform/bootstrap inputs. Record validity does not authorize the record's
requested repository, project, environment, or privilege: protected inventory
review and explicit operator authority must authorize those bindings.

| Concept carried by the common record | GCP interface obligation |
| --- | --- |
| Deployment identity and installation profile | Stable deployment ID selects ownership/state. The existing root installation config still passes `load_root_config`; `deployment.profile` selects supported behavior, never a tenant. GCP currently supports `dev` and `prod`; image lane `proof` is not therefore a supported installation profile. |
| Cloud placement | Bind project, region/zone, resource names and state locations explicitly. Platform, identity, image-source/target, secret-store and runner projects may differ only through authorized resource-owner grants. |
| Purpose bindings | A closed set of supported capabilities (`build`, `validate`, `promote`, `release_scan`, `deploy`, `destroy`) maps enabled purposes to distinct accounts and exact execution contexts. Enabling deploy must not implicitly enable an image lane. Promotion has explicit source and destination ownership. |
| Execution provenance | Inventory repository/revision, product source revision, executing repository, protected full ref, caller workflow and reusable workflow revision are distinct identities. Exact purpose Environment subjects and workflow claim expectations derive from this context. No source/runner/repository fallback from the current directory or Git remote. |
| Bootstrap and secret inputs | Reuse #2178's common references and resolver with explicit store/repository/environment scope. Installation secret references still pass backend grammar checks. Identity provider paths and account emails are non-secret bindings, not authentication credentials. |
| Ownership and reconciliation | Separate state addresses for foundation identity, runner and platform; explicit ownership for GitHub Environments and policies. Outputs identify the applied revision and verified bindings without embedding credentials or a second desired-state store. |

An unseen ID is configuration, not a new profile, branch, module, workflow,
overlay, or product clone. A temporary checkout of an immutable product revision
is ordinary execution machinery; tenant patches and permanent copies are not.
Deployment ID, DNS name, GitHub Environment, image lane, IAM purpose, application
workspace/organization, and backend selector must remain separate concepts.

## Trust and bootstrap decisions

Preserve `global/cicd-oidc` and `modules/cicd-oidc-identity` as the foundation
owner. Model trust as authorized tuples of repository, purpose subject,
protected ref and workflow context. Derive both the provider union and each
account's exact `principal://.../subject/...` bindings from the same validated
purpose mapping. Subject sets are pairwise disjoint; tuple pairing must survive
rendering (independent lists must not create an unintended Cartesian product).
Disabled purposes have no federation or effective capability. A finite purpose
enum is appropriate; an enum of deployment names is not.

Do not accept arbitrary CEL, HCL, IAM roles, commands, workflow paths or backend
options as unrestricted inventory extensions. Capability policy remains product
owned; records select approved capabilities and their scoped resources. Preserve
the #1699/#2084 permission and evidence boundaries, including build self-`actAs`,
no-SA validation guests, target-owned promotion, read-only release scanning,
and prefix-conditioned private evidence. Existing deploy/destroy IAM and secret
administration are powerful: examine effective escalation through project IAM,
service-account policy and impersonation, not just declared role names. A new
bootstrap binding must not let routine CI rewrite its own trust or grant another
purpose. In particular, the current `deploy_roles` and `destroy_roles` include
`roles/resourcemanager.projectIamAdmin` and `roles/iam.serviceAccountAdmin`;
copying them unchanged is not evidence of that isolation. Resolve the effective
IAM-administration boundary before activating generic trust, including inherited
grants and access to foundation state. Do not claim stronger isolation than
effective provider tests prove.

Bootstrap starts with an explicitly identified operator's cloud authority and
separately scoped GitHub administration authority; it cannot depend on the WIF,
runner, secret binding or state bucket it is creating. Verify the actual ADC /
gcloud / Terraform backend and provider principals, target projects and GitHub
repository before mutation. Reuse existing bootstrap credential context handling;
ambient credential precedence must not silently change the actor. Initial
authority covers only the required API/state/IAM and GitHub Environment/runner
operations, is documented separately from steady-state CI, and uses no static
service-account keys or project Owner shortcut.

The incumbent `gcp_terraform_bootstrap_credentials` currently creates a real
service-account key and later revokes it; a temporary file does not make that
flow keyless. Reuse its credential-context restoration/cleanup seam, but choose
explicit operator ADC or authorized short-lived impersonation for this flow.
Do not silently call its key-creation path or fall back to it when organization
policy rejects key creation. Its grants/revocation and runner registration also
need bounded retry and failure cleanup. The working-tree runner change adds an
EXIT cleanup trap; verify failure, interruption and registration retry behavior
before crediting it as protection.

Reconcile GitHub execution Environments through common bootstrap tooling, with
protection/approval policies verified before federation is usable. Never rely on
an implicitly created unprotected Environment, confuse branch protection with
environment deployment policy, or let a read-only PR activate trust. Read back
subject-template settings and actual repository/environment/ref/workflow claims;
default subjects omit workflow identity. Cross-repository reusable execution
must constrain the actual caller and reusable-workflow claims at the provider,
not trust a path string supplied by workflow input. Missing/mismatched claims
fail closed. Subject escaping (including reserved Environment characters) must
match real tokens; reject unsupported forms rather than interpolate them.
Bind numeric repository and owner IDs as well as the exact repository name;
Google documents name-reuse risk in its [deployment federation guidance](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).
For reusable jobs, distinguish caller claims from `job_workflow_ref` and its
immutable revision, as specified by [GitHub's reusable-workflow OIDC contract](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows).
Validate the resulting subject and CEL against provider size limits. Exact
subject principals are pool-scoped: another provider in that pool must not be
able to mint the same authorized subject under weaker conditions.

Changing execution repository also changes runner registration/access, private
workflow access, checkout credentials, GitHub Environment secret resolution,
artifact API authorization and evidence provenance. `GITHUB_TOKEN` access to a
different private repository must be proven, not assumed. Reuse exact artifact
ID/run/attempt/revision/digest verification in the Packer evidence scripts;
the evidence producer repository need not equal the deployment repository.
Record any narrow cross-repository credential as a common secret reference.
Keep evidence private and the public verdict redacted. The product repository
remains `Brad-Edwards/shifter` for issue/PR/traceability operations.

## Cross-cutting layers and canonical incumbents

| Layer / incumbents | Required behavior and known trap |
| --- | --- |
| Parsing/config: `installation/loader.py`, `schema.py`, `registry.py`, `settings_gcp.py`, `contract`, published contract/tests | Reuse duplicate/merge-key rejection, closed models, version/backend/profile validation, normalization, secret grammar, `ConfigIssue` and `InstallationConfigError`. The common inventory loader owns additional execution/bootstrap metadata; do not jam it into closed backend settings or duplicate root validation in shell. Treat downloaded inventory as data, with bounded parsing, immutable revision and controlled path resolution. `Path.resolve()` alone is not containment: reject inventory traversal/symlink escapes from its declared root. |
| Pre-mutation checks: `scripts/bootstrap/preflight.py`, `bootstrap_core.py`, `gcp_control_plane.py` | Reuse tool/secret checks, `PreflightReport`, security-input validation and dry-run behavior. `_gcp_secret_checks` still requires `SHIFTER_CONFIG_GCP_DEV`; `cloud_env_from_root_config` returns the profile. Generalization must pass deployment context separately rather than using either as tenant selection. Required values fail before authentication/apply; bootstrap checks must not circularly require a working deployment. |
| Terraform input/naming: existing GCP roots/modules and `validation-inventory.yaml` | Validate actual provider name/length constraints after derivation, uniqueness and ownership. Root deployment names allow 40 characters; service-account names derived by stripping hyphens have tighter limits and can collide. Preserve legacy names explicitly; never silently truncate or rename them. Safely serialize data; reject HCL/CEL/control-character injection and backend/path selection outside approved roots. Keep defense-in-depth module invariants without another inventory schema. |
| Federation and IAM: `check_tf_gcp_wif_trust`, `cicd-oidc-identity`, `portal/iam`, `packer-build-infra` | Check issuer/audience, exact repository/ref/subject/workflow tuples, disjoint account bindings, resource ownership and effective permissions. Preserve explicit deploy/build account outputs, node-SA `actAs`, scoped buckets, source-image reads and private evidence exclusions. Repository identity must resist unintended reassignment; establish immutable repository/owner claims where supported and verify the configured claim policy. |
| Workflows: `deploy.yml`, `_gcp-dev.yml`, `gcp-dev-destroy.yml`, `packer-gcp*.yml`; ADR guard `_workflow_model*`, `_deploy_workflow_*` | Keep PR validation GitHub-hosted, job-local permissions, protected environment binding, pinned actions/product code, explicit secret forwarding and fail-loud routing. Today paths, runner labels, secret names and dispatch choices are tenant-specific. #2178's common workflow seam must replace them once; no #2182 workflow fork. Extend semantic runner-exposure/routing checks so a new label or dynamic input is not misclassified as safe. |
| Runner host: `gcp_runner.py`, `runner.py::mint_registration_token`, `global/github-runner`, `check_tf_gcp_runner_network` | Reuse target DTOs, IAP transport, bounded readiness/registration checks and failure aggregation. Preserve dedicated private VPC, no public NIC, least-privilege host identity and no default runner labels. Labels route jobs; repository/group/workflow restrictions authorize access. Do not share a credential-bearing host across untrusted deployments. Registration has a known brief remote `config.sh --token` argv exposure on the isolated host; do not expand it to shared hosts or claim stdin removes this residual. |
| Secrets and OS process boundary: `bootstrap_core.run_cmd_secret_stdin`, `gcp_terraform_bootstrap_credentials`, `docs/dev/deploy-secrets.md` | Resolve values only at their consumer; use stdin or protected temporary credential files, restrictive permissions from creation, cleanup on failure and no shell tracing. Never put tokens in local argv, Terraform vars/state, metadata, workflow outputs, plans or logs. `_validate_argv` checks types/NUL only; log redaction does not prevent OS argv exposure. Inherited `TF_*`/cloud credentials also require intentional handling. Never source inventory as shell. |
| Errors and observability: installation errors, `PreflightReport`, bootstrap `info/error`, workflow annotations, cloud/GitHub audit | Reuse existing error/reporting surfaces; emit bounded stage/status, safe deployment identifier and revision correlation. Do not dump private inventory, rejected Pydantic values, secret references, provider responses or raw subprocess exceptions. `run_cmd` prints `CalledProcessError`/stderr and is unsuitable for secret-bearing operations; use the secret-safe path and sanitize retrieval failures. Do not introduce a Django error envelope, exception tree or logging service for operator CLI work. |
| Runtime projection, only where forwarded: `GeneratedOutput`, `runtime_inventory_gcp.py`, `scripts/gcp/render_runtime_env.py`, `config/env-manifest.json`, `entrypoint.sh` | Feed existing normalized installation config into existing renderers. Preserve output role/destination/sensitivity classification and reference-only public config. CI trust metadata is not application runtime config. Any actual runtime binding change must also pass `_runtime_env`, `_cloud`, `_oidc_settings`, secret hydration, task-env allowlists and Kubernetes admission/base-chart parity. Cloud bootstrap does not confer Django staff/superuser authority. |

Reuse must preserve behavior across serialization boundaries. The existing
`read_gcp_control_plane_security_inputs` reads HCL `terraform.tfvars` and
`*.auto.tfvars` with regexes; it does not read a new JSON projection or every
Terraform override source. The common projection must reach the same security
validator and applied inputs, preserving managed TLS, hostname and private
control-plane CIDR checks. Do not add a competing parser or bypass this gate
because generated files moved outside the environment directory. Use structured
serialization and explicit data arguments across HCL/JSON, shell, runner remote
commands and GitHub env/output files; reject option injection and newline or
delimiter injection. `_validate_argv` and shell quoting alone do not cover all
of these formats. Keep `secret_hygiene`, `.gitleaks.toml` and output-classification
checks effective for generated external inputs as well as repository files.

## Determinism, state ownership and migration

Reuse bootstrap CLI orchestration and backend handling, extending their existing
seams rather than adding a second provisioning controller. Current runner init
uses the fixed `github-runner` prefix and identity docs use `cicd-oidc`: a shared
project/bucket needs deployment-scoped locations, not just a different tfvars
file. Foundation identity and runner state must outlive platform teardown.
State IAM must enforce the intended deployment boundary; different prefixes with
bucket-wide write permission do not establish isolation. Shared resources need
one declared owner, never competing authoritative IAM bindings in two states.
The legacy evidence bucket is `${project_id}-release-evidence`, independent of
deployment ID; Packer workflows also derive that name. Two identity roots in
one project must not both create or own it. Carry explicit evidence-store
ownership/locator through the common context and existing
`verify-build-evidence.sh` / `verify-promotion-evidence.sh` contracts, preserving
prefix permissions and legacy locators during migration. A new deployment is
not automatically a new evidence producer or promotion destination.

Use per-run Terraform working/data directories and protected generated inputs
outside source, native backend locks, and serialization keyed by deployment and
stack. Different repositories' workflow concurrency groups are not a shared
lock. GitHub policy reconciliation also needs single-writer ownership/conflict
detection. Stable keys, sorted rendering and immutable inventory/product revisions
make retries reproducible. A repeat run verifies existing resources/policies;
it does not rotate secrets, replace accounts or append duplicate grants. Partial
failure reports the completed boundary and resumes reconciliation without
undoing unrelated resources or widening trust. Protected state/plan handling,
versioned backups and explicit backend migration remain mandatory.

Migration must inventory actual state addresses and remote ownership before
moving anything. Preserve existing pool/provider, account IDs, IAM members,
custom roles and evidence bucket ownership, including the unconditional legacy
`packer_build` account and indexed purpose accounts. Use reviewed Terraform
moves/imports/backend migration where addresses change; an empty destination
state is not permission to recreate resources. Account for retained/locked
evidence and resources whose names cannot safely be reused. Keep one active
writer and verify plans do not replace identity foundations or destroy them.

Repository trust cutover requires protected target Environments and access
readback first, exact authorized tuples only, and explicit removal of old
repository/branch grants. If overlap is required, it must be separately reviewed
and bounded; do not silently union old and new trust for compatibility. Rollback
restores reviewed ownership and exact policy, never wildcard trust. Retire
`nazgul`, `gcp-dev`, `proof` and `prod` tenant-selector branches after their
corresponding configurations migrate; historical fixture IDs may remain as
migration evidence, not executable dispatch policy.

## Verifiable rendering and acceptance evidence

The committed WIF guard parses literal `gcp-dev`/`nazgul`/`proof`/`prod` ternaries;
the working-tree replacement checks a generic source expression and resolved
plans. Switching Terraform to `join()` alone does not preserve coverage. Evolve that same guard
to validate the resolved provider condition and IAM graph from the common
projection. Use a deterministic, concrete Terraform rendering/plan surface
that the pinned Checkov invocation demonstrably checks, and bind it to the
exact configuration/plan applied. A separate example CEL file, a checker that
only finds strings, or tests that repeat the renderer are insufficient.

Keep blocking Checkov and `CKV_GCP_125` coverage with no skip or soft-fail.
Demonstrate a bad condition produces an actual failure, not zero discovered
resources or unresolved values. Fail on missing/unknown policy inputs or scan
coverage. If the pinned scanner cannot inspect the chosen surface, resolve the
rendering/scanner integration before shipping; this note grants no exception.
Keep `platform/terraform/.checkov.yaml`, pre-commit/CI invocation parity and module discovery in
sync, and document the changed enforcement mechanism under ADR-004-R23.

Required implementation evidence includes:

- An unseen ID and two deployments sharing a project: valid onboarding, no
  product edits, distinct ownership/state, no-op repeat, safe update, concurrent
  runs, failure/resume and platform destroy/rebuild preserving foundations.
- Existing installation contract/parsing/published-schema tests, bootstrap
  preflight/CLI/runner tests, Terraform validation inventory, WIF semantic tests,
  workflow routing/exposure and Packer provenance tests extended at their owners.
- Independently evaluated allowed and denied authentication tuples: wrong
  repository/owner, environment, ref, caller/reusable workflow, purpose/account,
  issuer/audience; PR/tag/unprotected ref, disabled purpose, cross-deployment
  impersonation and unsupported subject shape. Include malformed/injected
  configuration, naming collisions, state mixups and secret-safe failure tests.
- Provider-side readback and real representative authentication/permission
  probes for the selected repository and Environments. Fixtures and Checkov
  cannot prove installed policy, repository access or effective IAM isolation.
- Migration plans and ownership evidence, including old-trust removal and safe
  rollback. Keep private evidence private; report only sanitized results.
- `adr_guard --all --level ci`, Terraform fmt/init/validate, recursive TFLint,
  blocking Checkov and invocation parity, and `actionlint` for workflow changes;
  runtime/import/Kubernetes checks when those boundaries actually change.

## Draft integration guardrails

These are unresolved interface obligations, not an implementation sequence or
approval of the uncommitted implementation:

- **One common contract.** Reuse `loader.validate_root_config_data` for embedded
  installation intent. The draft `DeploymentRecord` and `SecretReference` must
  become #2178-owned contracts, not an independently versioned GCP dialect.
  Installation secret keys, logical bindings and provider resource references
  are different shapes; define their conversion once. GitHub secret consumption
  must match an enabled purpose's exact repository/Environment, not merely a
  caller-supplied Environment string. Cloud retrieval must use the verified
  consumer identity. References being syntactically valid is insufficient.
- **Credentials through the last hop.** `inventory_cloud.operator_environment`
  and the runner's `wait_for_runner_ssh` / `register_runner` use different process
  paths. Pass the verified credential context through IAP, registration and
  readback as well as Terraform; returning to ambient gcloud credentials loses
  the operator binding. Bound token lifetime/refresh and retries without changing
  principals. Child environments are process-visible credentials too: isolate
  the host/user, suppress diagnostic dumps, and pass credentials only to needed
  children. Preserve the noninteractive environment behavior in
  `bootstrap_core._subprocess_env`; consolidate secret-safe captured execution
  there rather than growing a second generic subprocess framework.
- **Actionable, safe failure.** Preserve `ConfigIssue`'s canonical field/stage
  and remediation hint with a bounded reason, without raw keys or rejected
  values. Collapsing every error into “record invalid” or “command failed” loses
  PLAT-005's clear-error requirement. Validate JSON response shapes before
  indexing; distinguish absence, forbidden access and transient failure. Cleanup
  failures must not mask the primary error. Retry only idempotent operations,
  respect throttling, and retain sanitized reconciliation progress.
- **Execution capability seam.** `PURPOSE_WORKFLOWS`, the CEL renderer and the
  semantic guard must agree on supported caller event and reusable workflow
  requirements. The draft fixes `workflow_dispatch` and makes the reusable claim
  optional; prove this covers every authorized caller. Omission cannot disable
  a capability's required workflow check. Extend product capability policy once
  for a future supported trigger; deployment records only select allowed tuples.
  Case-insensitive Environment ownership must still render the exact token
  subject; validate the complete derived subject length, not just each field.
- **Reviewable reconciliation.** Before first mutation, report a redacted diff of
  state creation, GitHub policy and identity/runner changes, including initial
  prerequisites when no state bucket exists. A plan must not silently bootstrap
  infrastructure. Reconcile all Environment protection types and administrator
  bypass policy, with readback; preserving only known reviewer/wait rules cannot
  justify overwriting unknown protections. Cross-record ownership checks must
  include runner names, backend bucket authority and overlapping prefixes.
  Explicitly scoped shared-project support must preserve IAM isolation; separate
  project names alone do not prove absence of inherited grants. Recover stale
  locks through reviewed ownership checks, never unconditional lock deletion.
- **Enforcement continuity.** The draft's two-check saved-plan scan supplements
  the full blocking source scan. It cannot replace it. `_resolved_plan.py` needs
  independently authored malformed/unknown/extra-grant cases and effective IAM
  checks beyond string equality. Register new Terraform contract tests through
  `scripts/check_tf_roots` / `validation-inventory.yaml` and new Python tests in
  the owning CI invocation; a test file existing does not mean CI runs it.
  Required generic module inputs also require a valid transition for every
  registered root and existing caller before retiring legacy dispatch logic.

## Non-goals and anti-patterns

No application tenancy/RBAC redesign, new API/controller/DTO/database,
provisioner abstraction, secret store, promotion registry, or general workflow
engine. PLAT-005's full runtime configuration, limits/quotas and startup coverage
are broader than this issue: do not claim them complete from identity bootstrap.
The payload's missing-provider-selector observation is stale: `_runtime_env.py`
already validates `CLOUD_PROVIDER` through the installation registry. Reuse it
and Django's existing `ImproperlyConfigured` startup boundary, with no new cloud
selector or CI trust settings in application code.
No AWS implementation here: #2178 owns provider-neutral contract and
workflow integration. No per-tenant Terraform/module/workflow copies, profile
allowlist growth, branch-derived provider selection, raw policy escape hatch,
shared purpose credential, static service-account key, or second validator/error
hierarchy. This preflight does not bootstrap resources, alter live GitHub policy,
resolve secrets, run authentication probes or claim the acceptance tests pass.
