# External deployment inventory contract v1

Issue #2182 establishes the common contract requested by #2178 and supplies its
GCP identity/bootstrap consumer. The canonical types live beside the existing
installation contract in `shifter/installation/deployment_inventory_types.py`;
`deployment_inventory.py` reuses the canonical YAML and installation validators.
The published JSON Schema describes shape. Python validation additionally checks
profiles, backend rules, purpose ownership, derived provider names and cross-record
collisions. The envelope keeps CI trust metadata out of application settings.

| Field | Owner and meaning |
|---|---|
| `version` | Common envelope schema, currently integer 1 |
| `installation` | Existing RootConfig: backend/profile/settings and logical secret bindings |
| `product` | Canonical product repository and immutable reviewed commit |
| `execution` | Private GitHub repository, immutable IDs and complete purpose context tuples |
| `state` | Explicit identity/runner/platform bucket ownership and prefixes |
| `secrets` | Common GCP/AWS/GitHub references; no secret payloads |
| `gcp` | Resource names, runner zone and closed capability inputs; project comes from `installation.settings.project_id` |

Inventory selects product capabilities; it cannot supply arbitrary HCL, CEL,
commands, IAM roles or Terraform flags. Purposes are build, validate, promote,
release_scan, deploy and destroy. An omitted purpose receives no federation grant.
Installation profiles and application tenancy retain their existing contracts.

## Authority and provenance

A valid record alone grants no authority. Bootstrap requires an explicit repository,
deployment project, gcloud account and GitHub administrator. Git origin and exact
commit are checked; records are bounded regular blobs read from that commit, not
mutable working files. Local record loading uses directory descriptors and
`O_NOFOLLOW`, rejects special files, and caps bytes before YAML parsing. Duplicate
and merge keys use the existing parser's rejection path.

The product runs from the chosen clean immutable checkout. Terraform execution
stages only tracked root/module code, lockfiles and the product-owned runner binary
pin into private temporary directories. Operational tfvars, cached provider files,
credentials and local state are never copied. There is no permanent per-deployment
product fork. Runtime and runner operations carry the same verified short-lived
operator credential through the existing subprocess boundary.

Both Terraform adapters use `inventory_plan.py` to retain private binary/JSON plans
and emit summaries of addresses and actions before apply. The CLI requires a new
operator-selected evidence directory and records immutable inventory/product
provenance there. Temporary execution cleanup does not delete review evidence.
GitHub Environment reconciliation matches names case-insensitively and verifies
that existing approval, self-review, wait and administrator-bypass settings survive.

Cloud roles remain product-owned. One GCP project hosts the application, runner,
automation identities, state and evidence. The project ID is supplied once in
`installation.settings.project_id`; the contract has no topology selector or
additional identity/runner project fields. The example also keeps secrets in that
project. Optional two-project support is deferred to
[#2189](https://github.com/Brad-Edwards/shifter/issues/2189).

Deploy and destroy retain the existing project IAM and service-account
administration permissions required by platform Terraform. These are trusted
administrative jobs: they can change project access, including their own access.
Exact WIF subjects prevent an unauthorized caller from logging in, but do not
contain an already authorized project administrator. Separate purpose accounts
and bucket grants describe the intended permissions, not an independent security
boundary against those administrators. Protected workflow code, repository access
and deployment approvals are therefore part of the administrative trust boundary.

Separate buckets scope each stack's direct state grants; prefixes alone do not
scope bucket IAM. Cross-record validation rejects duplicate deployment IDs,
buckets, purpose subjects, identity/runner names and deployment projects. Each
deployment owns its project. External bucket read grants are explicit capabilities,
not ownership claims.

## Exact WIF verification

`deployment_identity_gcp.py` projects complete repository/Environment/ref/workflow
tuples into the existing identity module. A provider condition requires the exact
repository name, numeric repository and owner IDs, `workflow_dispatch`, and a union
of complete subject/ref/workflow tuples. Reusable workflows additionally bind
`job_workflow_ref` to the reviewed product commit. Each purpose has a disjoint
Environment subject and exact `principal://.../subject/...` account bindings.

The existing source WIF guard now checks one generic product template instead of
enumerated tenant literals. Native Terraform tests exercise unseen inputs through
the real module and are registered in the Terraform CI validation inventory.
Bootstrap inspects the actual saved Terraform plan, rejects unknown/widened trust,
missing or extra account bindings and destructive identity changes, and runs pinned
Checkov on that plan. It hashes the plan and applies those exact bytes. The ordinary
repository-wide blocking Checkov suite remains required; targeted plan scanning
supplements it. Installed provider and account policies are read back through the
same semantic verifier after apply.

Checkov's source/parser check is not an authentication proof: its substring analysis
can accept boolean bypasses such as `true || ...`. Exact semantic comparison rejects
those bypasses; generated private workflows test allowed impersonation, an invalid
audience and cross-purpose denial against Google. The inventory explicitly selects `default` (legacy names) or `immutable` (names
plus numeric owner/repository IDs). Bootstrap verifies the exact effective prefix;
new repositories require `immutable`. Both formats also bind the numeric claims.
The bootstrap scanner adapter extends only the pinned CKV_GCP_125 repository
parser for GitHub's immutable syntax. It refuses an unexpected scanner version or
parser pattern and preserves upstream evaluation, reporting and failure status.
The ordinary repository scan remains unchanged; the adapter scans the exact live
saved plan after independent full-policy verification.
No CKV_GCP_125 waiver or ignored scanner failure is introduced.

## Persistence, errors and migration

A conditional GCS object acquisition serializes the deployment bootstrap; native
Terraform locking protects each state. Existing Environment reviewer and timer
policies are preserved while exact branch policies reconcile. Healthy runners are
reused; failed registration removes its temporary token file. Only bounded stage,
exit status and remediation reach errors; child payloads remain private.

Existing resource addresses and naming derivation are preserved. Destructive
identity updates are rejected. Application resources, runners and automation
identities share the deployment project, with separate state ownership as described
above. This gate does not establish that an existing deployment has migrated.
See the [operator migration procedure](../dev/gcp-inventory-bootstrap.md).

The shared secret resolver retrieves references only at the consumer. GCP uses
explicit numeric versions, AWS uses a scoped ARN (the current version), and GitHub
uses an injected secret with exact repository/Environment matching. Outputs are new
private files with consumer-owned cleanup, not Terraform input or state.

PLAT-005's broader runtime configuration, quotas and startup validation remain
owned by the existing installation/backend/runtime boundaries. This delivery extends
its external configuration enforcement; it does not redefine those requirements.
