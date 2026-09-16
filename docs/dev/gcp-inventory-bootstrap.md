# Bootstrap GCP from private deployment inventory

The `inventory` commands provision GCP CI identities, protected GitHub
Environments and dedicated runners from an external deployment record. They do
not deploy the application. The shared envelope also supports AWS installation
intent and secret references; AWS bootstrap remains a separate consumer.

## One project per deployment

Use one GCP project for the application, runner and automation identities. There
is no project-topology choice to configure. The bootstrap creates the required
buckets and service accounts within that project. Optional two-project support is
tracked in [#2189](https://github.com/Brad-Edwards/shifter/issues/2189).

Deploy and destroy workflows administer the project and can change its access
permissions. Their separate service accounts and exact login rules protect entry
to the workflows; they do not contain a compromised administrative workflow.
Treat access to those workflows like access to a project administrator.

## Prepare the two repositories

Create a private execution/inventory repository with a protected `main` branch.
Bootstrap requires a GitHub administrator for that repository and a gcloud
operator with authority to manage the selected project, state buckets, service
accounts, IAM and runner infrastructure. The operator is the account shown by
`gcloud auth list`, which may be an email address. A project ID is a resource
container, not a login account.

Use a temporary checkout of an immutable product commit. No permanent deployment
branch, product fork or tenant-specific product source is needed. Install the
bootstrap package with `uv sync --project scripts/bootstrap`. The required CLIs
are Git, gh, gcloud, Terraform 1.16.1 and uv. Checkov is invoked at the product
pin automatically from its immutable source commit (the matching release is not
available from the package index). Export the appropriate `GH_TOKEN` through your existing
credential mechanism; do not put credentials in the inventory.

Copy `shifter/installation/examples/deployment-inventory.json` into the private
repository as `deployments/<deployment-id>.json`. The example is neutral and
intentionally cannot operate on a real account unchanged. Supply:

- The installation profile and provider settings accepted by `shifter-config`.
- An immutable product commit, private execution repository and numeric
  repository/owner IDs (`gh api repos/OWNER/REPO --jq '{id, owner_id: .owner.id}'`).
- Exact workflow filenames, protected branch refs and distinct purpose
  Environments. A deployment ID, installation profile and IAM purpose are
  different fields. Do not reuse an Environment across purposes.
- One GCP project ID in `installation.settings.project_id`, plus the region and
  runner zone. Shifter, its runner and automation service accounts use this project.
  The example keeps Secret Manager resources in the same project too.
- Dedicated identity, runner and platform state buckets and prefixes. Each stack
  needs a distinct bucket because IAM grants apply at bucket scope. Preserve the
  exact existing names when migrating. The evidence bucket is separate too.
- Logical secret bindings. GCP references include a specific Secret Manager
  version; AWS references use Secrets Manager ARNs; GitHub references name a
  secret in the exact execution repository and Environment. Never enter payloads.

Commit the record. Keep the inventory checkout at that reviewed commit. The
loader verifies its origin, commit, regular Git blobs, input bounds and ownership
across every committed `deployments/*.{json,yaml,yml}` record.

## Validate and generate execution checks

Run from the immutable product checkout, substituting your own paths and SHAs:

```bash
uv run --project scripts/bootstrap python scripts/bootstrap/deploy.py inventory validate \
  --inventory-root /path/to/private-inventory \
  --inventory-repository OWNER/REPO --inventory-revision INVENTORY_COMMIT \
  --record deployments/customer.json

uv run --project scripts/bootstrap python scripts/bootstrap/deploy.py inventory scaffold \
  --inventory-root /path/to/private-inventory \
  --inventory-repository OWNER/REPO --inventory-revision INVENTORY_COMMIT \
  --record deployments/customer.json --output /path/to/new-private-starter
```

Copy the generated `.github/workflows/` into the private repository, review and
commit them. Use the new inventory commit for subsequent commands. These are
identity checks, not application deploy/destroy actions: the filenames correspond
to the approved purpose contexts. They verify pinned product access, allowed
impersonation, rejected alternate audience and rejected cross-purpose identity.
They run on the deployment's dedicated runner. Existing reviewed reusable
workflow callers must be retained separately; the scaffold refuses to pretend a
direct check has a reusable workflow's identity.

## Bootstrap and repeat

The first run requires explicit apply authority because buckets, Environments and
runner infrastructure do not exist yet:

```bash
uv run --project scripts/bootstrap python scripts/bootstrap/deploy.py inventory bootstrap \
  --inventory-root /path/to/private-inventory \
  --inventory-repository OWNER/REPO --inventory-revision INVENTORY_COMMIT \
  --record deployments/customer.json \
  --execution-repository OWNER/REPO --project PROJECT_ID \
  --operator OPERATOR_ACCOUNT --github-actor GITHUB_LOGIN \
  --plan-output /private/new-bootstrap-review --apply
```

The command checks authority before mutation, matches Environment names without
regard to capitalization, preserves and verifies existing reviewer/wait/self-review
and administrator-bypass protections, reconciles exact branch policies, and
configures the reviewed OIDC subject format. Set `execution.subject_format` to
`immutable` for new repositories; `default` preserves existing name-only subjects.
Immutable prefixes include both reviewed IDs (`repo:OWNER@OWNER_ID/REPO@REPO_ID`).
Bootstrap verifies `use_default`, `use_immutable_subject` and the exact
`sub_claim_prefix` before trust activation; it never silently falls back to another
format. Numeric `repository_id` and `repository_owner_id` remain mandatory in
cloud trust for both formats. A version-checked compatibility adapter extends the
pinned CKV_GCP_125 parser to accept immutable syntax, while preserving blocking
scan results and independent exact-policy verification. See
[GitHub's OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).

Bootstrap uses a short-lived token from the explicit gcloud account for both
Terraform and runner operations. It rejects impersonation/credential-file
configuration overrides and never creates service-account keys or changes the
active project. Native Terraform locks and a generation-guarded bootstrap lock
serialize writes. Identity plans must pass exact resolved-policy verification and
pinned Checkov before the saved plan is applied. Identity resource replacement is
refused. Bootstrap reads installed trust back and publishes non-secret identity
variables to the exact Environments.

After onboarding, use `inventory plan` with the same bindings, a new
`--plan-output` directory and without `--apply`. Existing buckets, subject settings
and Environment policies must already
match; plan takes a coordination lock but does not apply Terraform. A repeated
`bootstrap --apply` reconciles the same resources and skips healthy runner
registrations. After a failure, correct the named prerequisite and repeat; do not
change the deployment's state addresses. If a process was killed while holding
`<identity-prefix>/bootstrap.lock`, inspect it and verify the original process has
stopped before an operator removes it. The tooling never steals locks.

Each stack prints an action summary with resource addresses, action counts and
`has_changes` before applying. Both stacks also retain their binary plans, complete
before/after JSON and summaries in the requested `--plan-output` directory, along
with inventory/product provenance. The directory is mode 0700 and files are mode
0600; existing destinations are refused. These files can contain sensitive Terraform
values. Keep them private and out of Git, public logs and public artifacts.

For a migration or update, first run `inventory plan`, inspect both
`identity.plan.json` and `runner.plan.json` in that private directory, and review
removed principals and changed resources. Then run `bootstrap --apply` with a new
private output directory. That invocation creates and displays fresh validated
plans and applies those exact bytes; it does not reuse an earlier preview. A repeat
plan reports `has_changes: false` for both stacks when there is no drift. Full
before/after details remain available after temporary execution files are removed.

Dispatch the generated private workflows from the protected branch. Retain their
run URLs and the bootstrap's inventory/product revisions and plan hash in the
private repository. Check a second bootstrap for drift. Local mock tests and
Checkov results do not substitute for these live authentication checks.

## Resolve a secret for a consumer

`inventory resolve-secret` accepts the same inventory provenance flags plus
`--execution-repository`, `--execution-environment`, `--secret-name` and
`--secret-output`. It writes a new mode-0600 file and never prints the payload.
GitHub secrets must already be injected into the authorized Environment job;
cloud retrieval uses that consumer's existing credentials. The consumer owns
file cleanup. Resolution never gives the bootstrap identity runtime access merely
because a record names a secret.

## Migrate existing deployments

1. Keep the existing production execution revision in service while preparing
   inventory. The old tenant tfvars are not inputs to the generic root.
2. Record every existing Terraform state address, project, pool/provider name,
   account ID, evidence bucket and runner name. Take private state backups using
   the current backend. Freeze concurrent deployment/bootstrap writers.
3. Retain existing `name_prefix` values. Identity account IDs continue to derive
   from that prefix with hyphens removed; Terraform resource addresses remain
   stable. Use the same remote backend for each existing stack. If stacks
   previously shared one bucket, use Terraform's explicit backend state migration
   under operator authority to separate buckets before adopting this contract;
   never copy state into two active owners or initialize an empty replacement.
4. Keep the existing project. Deploy and destroy jobs retain the platform's
   administrative permissions; those jobs are trusted to administer this project,
   including project IAM. Review repository access, protected workflow code and
   Environment approvals before enabling the new execution repository. A second
   project or moving existing cloud resources is not required for adoption.
5. Move execution to the exact private repository and protected purpose
   Environments. Review the plan's removal of old principals and addition of the
   new exact principals. There is no broad dual-repository compatibility grant.
   Preserve existing resource names; unexpected replacement stops the migration.
6. Run the allowed and denied checks and a second no-drift bootstrap. Only then
   retire the old execution caller/tenant tfvars. Account or purpose removal that
   requires resource deletion is a separate reviewed decommission, not bootstrap.

This procedure applies to existing development deployments and image lanes using
their recorded names; the module contains no tenant-name switch. Live migrations
must be recorded per deployment before claiming those deployments are cut over.
