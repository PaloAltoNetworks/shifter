# Terraform Root Pull-Request Validation Preflight (#1528)

Status: pre-implementation guidance

Date: 2026-07-12

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1528>

This is a requirement-free architecture preflight. The GitHub issue is the
shipping contract. This note fixes the boundary between deployable/runtime
Terraform roots, reusable modules, pull-request validation, and live deploy
workflows; it does not implement the inventory, workflow, validator, or module
tests.

## Scope Boundary

The change is a hosted-runner pull-request quality gate. It must prove that an
affected Terraform root can install its locked providers without a backend and
that Terraform accepts the complete root composition. It must not authenticate
to AWS or GCP, read remote state, render deployment secrets, plan live
infrastructure, or route untrusted pull-request code to a self-hosted deploy
runner.

`terraform init -backend=false` plus `terraform validate` is one validation
layer. TFLint, Checkov, the repo-native Terraform security checkers, ADR guard,
and module contract tests retain their distinct responsibilities. Passing one
must not be treated as passing the others.

## Current Repository Findings

- Pull requests reach `.github/workflows/_quality.yml` through
  `.github/workflows/deploy.yml`. The quality workflow classifies one broad
  `terraform` category from `.github/quality-path-filters.yaml`, then runs
  TFLint and the repo-native `check_tf_*` checks. It does not run generic
  backendless root validation.
- `.pre-commit-config.yaml` already declares `terraform_fmt`,
  `terraform_tflint`, and `terraform_validate`, but the CI pre-commit job runs
  only file-hygiene and secret hooks. Local pre-commit is therefore a
  convenience, not the pull-request enforcement boundary.
- AWS core/range/platform deploy jobs run `init`, `validate`, and `plan` only
  on trusted non-PR paths. `_gcp-dev.yml` has a credential-free hosted
  validation job, but its caller currently excludes pull-request events. The
  generic gate belongs in Quality rather than in any deploy workflow.
- The repository currently has 18 Terraform execution roots, and every one has
  a committed `.terraform.lock.hcl`:
  - AWS environment roots: core, portal, and range under each of
    `platform/terraform/environments/{dev,proof,prod}` (nine roots).
  - GCP environment root:
    `platform/terraform/gcp/environments/gcp-dev`.
  - AWS global roots: `global/{iam,github-runner,dev-box,se-admins,ctfd-workshop}`.
  - Standalone Polaris root: `scripts/polaris-aws-range`.
  - Runtime roots:
    `shifter/engine/provisioner/terraform/modules/{range,ngfw}`. Despite the
    directory name, these are roots: the provisioner stages and executes them,
    and each declares a backend and owns a lockfile.
- There are 29 reusable-module directories. Thirteen decomposed GCP child
  modules correctly have no lockfile. A reusable module and an execution root
  are not interchangeable merely because both contain `*.tf` files.
- No `*.tftest.hcl` suites or Terraform fixture-plan suites exist today.
  Variable validation, root composition, the GCP facade checker, and static
  Python checkers cover parts of module behavior, but they are not module
  contract tests.
- Terraform consumers currently pin three toolchain versions: AWS deploy CI
  uses 1.13.3, GCP validation/deploy uses 1.7.1, and the provisioner runtime
  image uses 1.14.3. One unqualified CI version would validate some roots with
  a different parser/runtime than their consumer.

## Architecture Decisions And Guardrails

- Maintain one machine-readable inventory at
  `platform/terraform/validation-inventory.yaml`. It is the authoritative
  classification of Terraform directories for validation, not a copy of the
  AWS apply order, bootstrap backend registry, or deploy path filters.
- The inventory must be schema-versioned and classify every tracked directory
  containing Terraform source as either an execution root or a reusable
  module. Each root must have a stable id, normalized repository-relative path,
  validation owner, named toolchain profile, and provider requirements. Each
  reusable module must have an owner and an explicit contract-coverage state.
  Unknown keys, duplicate paths/ids, absolute paths, `..` traversal, missing
  directories, empty owners, and unclassified Terraform directories fail
  closed.
- Provider source addresses belong in the inventory because they select the
  no-credential validation profile. Version constraints remain canonical in
  Terraform `required_providers`; resolved versions and checksums remain
  canonical in each root lockfile. Do not reproduce version constraints in a
  third schema. After init, compare the inventory requirement with Terraform's
  own provider metadata rather than parsing HCL with regexes.
- Named toolchain profiles own the Terraform CLI version and provider-family
  environment hardening. A root references a profile; workflow YAML must not
  contain a parallel root-to-version case statement. The existing 1.13.3,
  1.7.1, and 1.14.3 consumer differences must either be represented or be
  deliberately unified and verified before the generic gate becomes
  authoritative.
- Every root validation uses its committed lockfile and the equivalent of:
  `terraform init -backend=false -input=false -lockfile=readonly -no-color`,
  followed by `terraform validate -no-color`. Missing, changed, or incomplete
  root lockfiles are failures. Reusable modules do not gain committed
  lockfiles merely to make them look like roots.
- A single repo-native helper should validate the inventory, select roots,
  emit the GitHub matrix, and invoke the fixed Terraform command shapes. Reuse
  the established `scripts/check_tf_*/` package-plus-unittest convention. Do
  not place a second inventory parser or command builder inline in workflow
  YAML or in the pre-commit hook.
- Root selection must be conservative. A root is affected by changes to the
  root, its lockfile, and every transitively consumed local module. Inventory,
  validator, toolchain, or workflow changes force all roots. Until a tested
  reverse local-module dependency closure exists, validate all registered
  roots for any Terraform-relevant change. Direct path-prefix matching is not
  sufficient: it misses shared modules and mishandles nested environment roots.
- Run root validation in `.github/workflows/_quality.yml` on GitHub-hosted
  runners with `contents: read`, `strategy.fail-fast: false`, and no deploy
  environment. The existing reusable-workflow failure and `PR Gate` already
  make a failed Quality job blocking; do not create a second PR gate.
- Keep `.github/quality-path-filters.yaml` as the canonical quality-change
  classifier. Its Terraform category must cover the inventory, validator,
  `platform/terraform/**`, `scripts/polaris-aws-range/**`, and provisioner
  Terraform roots. Do not add a competing path filter inside the validation
  job.
- The local pre-commit validation surface should call the same repo-native
  helper, or remain clearly non-authoritative. It must not carry different init
  flags, root discovery, exclusions, or exception behavior from CI.
- Module contract coverage is separate from root validation. Prefer
  `terraform test` with mock providers for provider-facing modules and
  provider-independent fixture plans only where they exercise a meaningful
  plan-time contract. The inventory may use a closed enum for contract mode
  plus a normalized test/fixture path; it must not contain arbitrary shell
  commands. A temporary `not-feasible` state needs a specific reason, owner,
  and reviewable expiry/issue rather than a silent boolean skip.
- Any root-validation exception is temporary architecture debt and belongs in
  `docs/adr/exceptions.yaml` with owner, reason, affected paths, and expiry.
  There must be no `continue-on-error`, `enabled: false`, empty matrix, or
  provider-error allowlist that lets an owned root silently bypass the gate.
- Update ADR-004-R2 with the implemented inventory and backendless PR gate in
  the same change that introduces enforcement. ADR-004-R6 (GCP TFLint),
  ADR-004-R11 (Checkov), and ADR-003-R5 (hosted PR trust boundary) remain
  separate, unchanged controls.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Boundary to preserve |
| --- | --- | --- |
| PR quality routing | `.github/workflows/deploy.yml`, `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml` | Add validation to Quality and let the existing `PR Gate` block. Do not route PRs into deploy workflows or duplicate path classification. |
| Local Terraform checks | `.pre-commit-config.yaml` Terraform hooks | Reuse the local entry point but centralize root discovery and init flags in the repo helper. |
| Terraform lint/security | `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `scripts/check_tf_*/` | Keep lint, static policy, repo-specific checks, init/validate, and contract tests as distinct layers. |
| Architecture policy | ADR-003 and ADR-004 in `docs/adr/index.yaml`, `scripts/adr_guard/adr_guard.py`, `docs/adr/exceptions.yaml` | Preserve hosted PR execution, blocking Terraform policy, and expiring exceptions. |
| AWS stack semantics | `docs/dev/aws-terraform-apply-order.md`, `scripts/bootstrap/terraform_backend.py`, `scripts/terraform/render_aws_backend_configs.py` | These own apply order and live backend rendering. They are inputs to review, not generic validation inventories and must not run on PRs. |
| Deploy prerequisites | `scripts/bootstrap/preflight.py`, reusable deploy workflows | Keep live tool/secret/account readiness separate from static backendless validation. |
| GCP composition | `platform/terraform/gcp/environments/gcp-dev`, `scripts/check_gcp_tf_modules/` | Validate the real GCP root and preserve the facade-layout check; do not mistake the layout checker for generic root validation. |
| Runtime Terraform | `shifter/engine/provisioner/terraform_base.py`, runtime root lockfiles, provisioner Dockerfile | Preserve lockfiles as reviewed source and `.terraform`/state/tfvars as runtime artifacts. Do not call the live backend runner from PR CI. |
| Secret/artifact hygiene | `.gitignore`, `.gitleaks.toml`, ADR-004-R7/R8/R14 | No rendered tfvars, live identifiers, state, saved plans, crash logs, credentials, or debug logs enter the validation path. |
| Review ownership | `.github/CODEOWNERS` | Inventory `owner` means validation responsibility. Do not silently generate or duplicate review rules; update CODEOWNERS deliberately if review ownership must also change. |

No application controller, DTO, service, repository, persistence schema, or
exception hierarchy solves this CI concern. Introducing one would cross the
wrong boundary. The established repo-native checker convention and GitHub
Actions quality workflow are the correct layer.

## Cross-Cutting Layers

| Layer | Required behavior |
| --- | --- |
| GitHub authorization | Hosted PR job, `contents: read` only. No `id-token: write`, deploy Environment, pull-request write, cloud role assumption, or self-hosted runner. The Terraform job must not receive `SONAR_TOKEN` or other reusable-workflow secrets. |
| Secret handling | Do not render `local.auto.tfvars`, read deployment secrets, invoke bootstrap preflight/backend renderers, or set live `TF_VAR_*`, AWS, or Google credentials. Provider-family profiles may disable metadata discovery (for example `AWS_EC2_METADATA_DISABLED=true`) but must not install fake credentials that could authorize an accidental API call. |
| Inventory/config shape | Validate schema before emitting a matrix. Paths are normalized, repository-relative, contained by the checkout, and passed as data to fixed argv; never interpolate inventory text into `eval`, `bash -c`, or an arbitrary command field. Provider/toolchain/mode values use closed enums or validated records. |
| Terraform parser/provider gate | Locked, backendless, noninteractive init verifies module/provider resolution and checksums; validate verifies the full root configuration. `-lockfile=readonly` makes dependency drift fail instead of mutating reviewed source. Root toolchain selection matches the consuming runtime. |
| Static security/policy | Existing TFLint, Checkov, `check_tf_*`, ADR guard, gitleaks, and actionlint continue to run. Root validation neither replaces them nor broadens/narrows their policy scopes accidentally. Checkov remains scoped by ADR-004-R11. |
| OS/process exposure | Use subprocess argv or quoted `terraform -chdir` paths, never shell evaluation. Set `TF_IN_AUTOMATION=1`; keep `TF_LOG` off. Root paths, provider source names, versions, and owners are non-secret; credentials, environment dumps, tfvars, state, and plan bodies never appear in argv or process listings. |
| Persistence/cache | Cache only the Terraform provider package cache under runner temp. Key by OS, architecture, exact Terraform toolchain, and root lockfile hash. Never cache or upload `.terraform/`, backend metadata, state, tfvars, saved plans, or crash logs. Lockfiles are the only persistent provider-resolution artifact. |
| Error envelope | Fail nonzero per root and keep matrix fail-fast disabled so all broken roots are visible. Diagnostics may name root id/path, owner, toolchain, provider, stage, and Terraform stderr. Do not print environment values, file contents, state, plans, or generated variables; do not enable provider debug logging. |
| Observability | GitHub job names/summary are the evidence surface. Report bounded per-root stage/status/duration metadata. Do not add a database, artifact telemetry format, cloud log sink, or second logging framework. |
| Exception handling | Use ordinary process exit status and concise typed validation diagnostics in the helper. Do not create an application exception hierarchy. Waivers flow through the existing ADR exception registry and expiry policy. |

## Extensibility Seam

The seam is a schema-versioned root record consumed by one selector/runner:
stable id, path, validation owner, toolchain profile, provider requirements,
and closed validation/contract modes. The next likely additions are a GCP
production root, another provisioner runtime root, or a new provider family.
Those must require an inventory record and profile addition, not edits to a
workflow case statement.

Affected-root selection is a replaceable policy behind the same inventory. A
conservative `all` selector can later become a tested transitive dependency
selector without changing root command construction or workflow trust. Keep
selection mode as an explicit helper input for full/manual validation; do not
encode it as per-root booleans or duplicate watch globs throughout YAML.

## Whole-Repo Scope For The Intended Change

The implementation is expected to touch only the relevant subset of:

- `platform/terraform/validation-inventory.yaml` and every registered root
  `.terraform.lock.hcl` that requires a deliberate lock refresh.
- One repo-native checker/selector package under `scripts/`, with focused
  unittests for schema, completeness, path containment, provider/toolchain
  selection, affected-root closure, and failure propagation.
- `.github/workflows/_quality.yml`, `.github/quality-path-filters.yaml`, and
  `.pre-commit-config.yaml` for the canonical CI/local entry points.
- `docs/adr/index.yaml` (ADR-004-R2), ADR enforcement/developer Terraform docs,
  and `docs/adr/exceptions.yaml` only for justified temporary debt.
- Terraform test files or fixture roots beside the modules they test, without
  adding lockfiles to ordinary reusable modules.
- `changelog.d/1528.changed.md` or `1528.fixed.md`, because CI behavior changes
  require a fragment under the repository workflow rules.

Host/runtime layers that see the result are GitHub-hosted Ubuntu runners,
Terraform CLI/provider subprocesses, the provider registry download path, the
Actions cache service, local pre-commit, and branch-protection's existing PR
Gate. AWS/GCP APIs, deploy runners, Terraform backends, application containers,
databases, and Kubernetes are explicitly outside the execution path.

## Gotchas And Anti-Patterns

- Do not classify every `*.tf` directory as a root. That creates child-module
  lockfiles, duplicates provider ownership, and obscures the two provisioner
  directories that really are runtime roots despite being named `modules`.
- Do not discover roots only by `backend` blocks. Polaris is a real root without
  a remote backend, while root intent is also established by runtime/workflow
  callers.
- Do not select a root only when a changed file is beneath that root. Shared
  local modules affect every transitive consumer; nested environment roots make
  naive prefix matching ambiguous.
- Do not duplicate root lists across workflow matrices, shell scripts,
  pre-commit args, bootstrap stack registries, and docs. The validation
  inventory is canonical for this concern; other registries retain their own
  narrower semantics.
- Do not hand-parse general HCL with regexes. Let Terraform resolve
  configuration/provider metadata; keep the repo helper focused on the small
  inventory schema and process orchestration.
- Do not run `terraform plan` against real environment roots on pull requests.
  Plans can evaluate data sources, require credentials/remote state, and expose
  sensitive values. Contract fixture plans must be isolated, synthetic, and
  provider-mocked or provider-independent.
- Do not use deploy tfvars, remote backend configs, AWS profiles, WIF/OIDC,
  repository cloud secrets, or dummy-but-usable credentials to make validation
  pass. Fix the root so init/validate is credential-free.
- Do not cache `.terraform/` directories or upload plan/state artifacts.
  Provider package caching plus readonly lockfiles is the reusable boundary.
- Do not let `terraform init` rewrite lockfiles in CI. A changed dependency is
  a reviewed source change, not an ephemeral workflow side effect.
- Do not use one Terraform version for all roots without reconciling the current
  consumer pins and the GCP 1.7.1 compatibility comments.
- Do not collapse TFLint, Checkov, ADR policy, init/validate, and module tests
  into one vague "Terraform validation" success. Their failure domains and
  waiver policies are different.
- Do not add `continue-on-error`, fail-fast matrix cancellation, unowned
  exclusions, or workflow-only skip lists. They defeat the issue's gate.
- Do not print `env`, `terraform.tfvars`, state, saved plans, provider debug
  logs, or cache contents while diagnosing a failure.

## Non-Goals

- No Terraform, workflow, inventory, validator, fixture, test, cache, or
  lockfile implementation in this preflight.
- No live Terraform plan/apply/destroy, backend initialization, state migration,
  cloud authentication, or deploy prerequisite validation.
- No unification or upgrade of Terraform/provider versions unless separately
  justified and verified; the gate must first represent the consuming
  toolchains accurately.
- No rewrite of AWS apply order, bootstrap backend ownership, GCP facade
  decomposition, provisioner runtime staging, or deploy branch routing.
- No expansion of Checkov/TFLint policy scope merely because more roots are
  inventoried.
- No new application config schema, API/controller/DTO/service/repository,
  persistence model, exception hierarchy, or logging/telemetry service.
- No Ground Control requirement or traceability object for this
  requirement-free issue.

## Validation Expectations

For this preflight documentation change:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/terraform-root-pr-validation-preflight-1528.md --level fast
```

The eventual guardrail/workflow implementation must also pass the repository
checks for its touched surfaces, including at minimum:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
actionlint
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

It must add focused tests proving inventory completeness, unsafe path
rejection, root/module classification, toolchain/provider selection,
transitive or conservative root selection, read-only lockfile behavior,
credential-free execution, all-root failure visibility, and no-op behavior for
unrelated changes.
