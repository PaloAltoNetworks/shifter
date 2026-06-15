# ADR Enforcement

Architecture rules in this repo are enforced by tooling, not just prose.

## What Exists

The current enforcement stack has six parts:

1. `docs/adr/index.yaml`
   Machine-readable ADR registry. Each accepted ADR lists the rules and the checks that enforce them.

2. `docs/adr/exceptions.yaml`
   Explicit exceptions. If a rule needs a temporary waiver, record it here with an owner and expiry instead of leaving the exception implicit.

3. `scripts/adr_guard/adr_guard.py`
   Repo-native policy runner. This is the entrypoint for ADR conformance checks.

4. `.pre-commit-config.yaml`
   Fast local enforcement. The ADR guard runs before commit so architectural drift is caught locally.

5. `.github/workflows/_quality.yml`
   CI enforcement. ADR conformance runs as its own architecture gate.

6. Existing ecosystem tooling
   - `import-linter` for Python package contracts
   - `actionlint` for GitHub Actions workflows
   - `TFLint` for Terraform linting (including the `tflint-ruleset-google` plugin for GCP resources)
   - `gitleaks` for new secret leakage detection
   - `helm lint` for Helm chart validation where files are templates rather than plain YAML
   - `kubeconform` for Kubernetes manifest schema validation
   - `kube-linter` for Kubernetes security and best-practice enforcement
   - `Checkov` for IaC security scanning (Terraform and Kubernetes)

There is also agent-specific wiring:

- `.claude/hooks/adr_guard_hook.py` runs the ADR guard after Claude edits files.
- `.claude/skills/adr-check/SKILL.md` provides a default workflow for ADR conformance work.
- `.claude/skills/architecture-review/SKILL.md` provides a repo-specific architecture review checklist.
- `AGENTS.md` gives Codex a repo-local policy file, including Ground Control project context for the `/implement` workflow. The GC project pointer (and matching `.ground-control.yaml` `project:` field) names the `shifter` project (id `df4e718f-1f67-46f8-a375-3ba53fabc9c4`) with `CTF-*`, `PLAT-*`, `GEN-*` UID prefixes by subsystem; an earlier draft incorrectly pointed both at `aphelion` (a separate, unrelated project).

Review controls:

- `.github/CODEOWNERS` requires review on guardrail files and shared/public architecture seams.
- `.github/pull_request_template.md` requires an ADR impact section on PRs.
- `.github/copilot-instructions.md` now points GitHub Copilot toward the same ADR enforcement model.
- `.github/workflows/_gcp-dev.yml` now pins `platform/k8s/gcp/overlays/gcp-dev/kustomization.yaml` image `newTag` values to `${SHORT_SHA}` before `kubectl apply -k`, preventing mutable `:latest` restarts from drifting to a different image than the commit being deployed.

## Current Checks

The first slice intentionally stays small:

- `adr-registry`
  Validates the ADR registry and exception files.

- `layer-imports`
  Enforces the existing cross-layer import policy from `scripts/check_layer_imports/layer_imports.yaml`.

- `guardrail-docs`
  Requires guardrail changes to update ADR or developer docs in the same change.
  This is a changeset-level check (needs to see multiple files) so it runs in
  pre-commit and `--level fast`, but NOT in the per-edit Claude hook.

- `cross-layer-model-imports`
  Fails on direct cross-layer model imports inside service layers. The current tree already satisfies this rule, so it is part of the default guard.

- `python-complexity-gate`
  Enforces ADR-012-R1: every canonical Python package `pyproject.toml`
  must enable Ruff's `C901` rule in `[tool.ruff.lint].select`, set
  `[tool.ruff.lint.mccabe].max-complexity` to the repo-wide threshold
  (`PYTHON_COMPLEXITY_THRESHOLD` in `scripts/adr_guard/adr_guard.py`,
  currently `15`, matching SonarCloud's default cognitive-complexity
  threshold), AND must not silently disable the rule by listing it in
  `ignore`, `extend-ignore`, or `per-file-ignores`. The check also
  cross-verifies that `PYTHON_COMPLEXITY_GATE_PYPROJECTS` matches the
  `id: ruff` hook working directories in `.pre-commit-config.yaml`, so
  a new lint surface cannot be added in one place without the other.
  The complexity computation itself is Ruff's job; this check is the
  config-shape backstop against silent gate removal. Existing
  high-complexity functions carry per-function `# noqa: C901`
  exemptions; the function-level backlog (one row per exemption with
  current complexity) lives at `docs/adr/complexity-backlog.md`. The
  threshold ratchets down as that backlog shrinks; a ratchet edit
  updates `PYTHON_COMPLEXITY_THRESHOLD`, every canonical
  `pyproject.toml`, and the backlog rows in a single PR. Runs in both
  `fast` and `ci` levels.
  Test coverage in `scripts/adr_guard/tests/test_adr_guard.py` drives
  the silent-bypass and prefix-selector cases through `subTest()` loops
  so adding a new bypass shape (for example, `extend-select`-side variants) is
  one row in the cases tuple, not a new test method.
  The `uat/event-load-harness` UAT load harness (#926) is a registered
  package under this gate, with matching `Lint`/`SAST`/`Tests
  (event-load-harness)` jobs in `.github/workflows/_quality.yml`.

- `boundary-mock-policy`
  Enforces ADR-019-R1: new Python tests may patch real process, network,
  cloud, and framework transport boundaries, but must not add new
  first-party internal callable patch targets. The check statically parses
  tracked test files for `patch()` / mock `.patch()` string targets and
  statically resolvable `patch.object(imported_module_or_class, ...)`
  calls, then compares `(test file, target)` counts against
  `scripts/adr_guard/boundary_mock_baseline.json`. The baseline records
  current legacy topology-coupled tests so adoption does not require
  rewriting the whole suite in one PR; the allowed counts may shrink but
  must not grow. The check also compares the baseline file against the
  branch reference so raising an allowance is a policy violation unless it
  has a dated ADR exception. Prefer behavioral assertions, in-memory fakes
  at service boundaries, or real framework test clients over patching
  first-party service functions, views, render/logging/transaction aliases,
  or model helpers.

- `import-linter`
  Adds package-level forbidden-import contracts across the main Django app layers.

- `actionlint`
  Lints GitHub Actions workflows beyond plain YAML validation.
  This includes the GCP deploy workflow's Terraform state-backend hardening
  (`_gcp-dev.yml`) so retention and IAM policy bootstrap logic remains valid.

- Django i18n/static artifact tests
  Enforce ADR-016-R3 in
  `shifter/shifter_platform/tests/config/test_i18n_configuration.py` and
  `shifter/shifter_platform/tests/platform/test_portal_dockerfile.py` by
  requiring portal image builds to run `compilemessages` before
  `collectstatic`, and requiring `entrypoint.sh` to stay free of runtime
  static-artifact rebuilds.

- `deploy-workflow-plan-scope`
  Enforces ADR-003-R2 for the AWS deploy workflows. The `shifter_platform`
  change filter in `.github/workflows/deploy.yml` must stay scoped to
  Terraform-consumed platform files. Quality routing is separate and runs by
  exclusion: `.github/workflows/deploy.yml` must expose a `quality_relevant`
  output that runs Quality unless the diff is ordinary docs-only. Guardrail
  docs, including `.github/pull_request_template.md`,
  `.github/copilot-instructions.md`, `docs/adr/**`, and this ADR enforcement
  page, are explicitly quality-relevant so ADR guard validates them. PR Gate
  must reject a skipped Quality job unless `quality_relevant` is false.
  Commit-message or label-based test skips are not accepted. Portal application
  changes must also keep
  reaching the portal image build/deploy path (#913): the check requires a
  `portal_image` filter covering `shifter/shifter_platform/**`, exposed as a
  `changes`-job output, included in the `shifter_platform` job's trigger
  condition, and consumed by the platform `build` job through the
  `portal_image_changes` input so an app-only push to an environment branch
  builds and converges the portal image without running Terraform. The check
  requires deploy concurrency to queue branch/manual runs rather than cancel
  in-flight applies; PR cancellation may remain enabled. It also requires every
  core, range, and platform `terraform plan` / saved-plan `terraform apply`
  command to include `-lock-timeout=5m`, and requires each apply job to create
  and execute a local saved `tfplan` instead of uploading raw binary plans as
  artifacts or running a fresh unplanned apply. The platform Service Discovery
  replacement check must inspect that same saved plan. Non-deploy support/test
  surfaces that are not under `shifter/**` or `mcp/**` must use the
  `quality_only` filter/output rather than being hidden in a deploy bucket:
  `scripts/polaris-aws-range/**` and `scenario-dev/polaris/tests/**` are
  required entries so the orphaned support suites run Quality without launching
  Terraform plans, image builds, or environment deploys. On apply workflows,
  `_shifter-platform.yml` still pushes the Guacamole ECR images before the
  platform Terraform plan because the Guacamole module resolves current image
  digests with `aws_ecr_image` data sources during plan. This ordering is
  required for fresh AWS accounts where the repositories exist but the tags have
  not been published yet.

- `portal-deploy-mode-source-of-truth`
  Enforces ADR-003-R4 for the AWS portal deploy path. `_shifter-platform.yml`
  must call `scripts/portal_deploy/portal_deploy.py resolve-topology` instead
  of reading `AWS_PORTAL_ENABLE_AUTOSCALING`; both AWS portal roots must export
  `enable_autoscaling`; the helper must reject single-instance deploys unless
  exactly one running tagged instance matches Terraform state; and the ASG path
  must call `verify-asg-image` after instance refresh so every in-service
  instance is checked for the new portal image tag.

- `deploy-verification-fail-loud`
  Enforces ADR-003-R3: deploy-verification steps must fail the run when the
  thing they verify did not happen, instead of warning and exiting 0. The
  `Wait for Guacamole ECS services to stabilize` step in
  `_shifter-platform.yml` must `exit 1` on stabilization timeout (the FAILED
  circuit-breaker branch already does); raise the poll timeout if first boot
  legitimately needs longer rather than downgrading the timeout to a warning.
  The `Update ECS task definition` step in `_shifter-engine.yml` must `exit 1`
  when the ECS task-definition family cannot be described, so a missing or
  typo'd family fails the deploy instead of silently skipping it forever; the
  only permitted skip is gated on the explicit `first_deploy` bootstrap input,
  surfaced as the `aws_first_deploy` `workflow_dispatch` input in `deploy.yml`
  (strict by default, settable to `true` only on a manual dispatch for the
  first-ever deploy to a fresh AWS environment).

- `TFLint`
  Adds Terraform linting on top of `terraform fmt` and `terraform validate`.
  The initial profile is intentionally narrow: it leaves existing repo-wide
  debt rules disabled so the new gate enforces signal instead of legacy noise.

- `gitleaks`
  Scans newly introduced commits for likely secrets, with a small repo config for approved false positives.

- `cloud-factory-seam`
  Enforces ADR-005-R1: every cloud adapter module in `cloud/aws/` must have a
  counterpart in `cloud/gcp/` and vice versa. Catches provider parity drift
  when one side adds a new adapter without the other. Runs in both fast and ci
  levels.

- `kubeconform`
  Validates Kubernetes manifests against official schemas. Catches misspelled
  fields, invalid resource types, and schema violations before they reach a
  cluster. Pinned to the target GKE Kubernetes version.

- `helm lint`
  Validates the Helm-packaged GCP control plane. This is the correct validation
  boundary for raw chart templates, which are not parseable by generic YAML
  tooling before render time.

- `kube-linter`
  Enforces Kubernetes security and best practices: non-root containers,
  read-only root filesystems, resource limits, privilege escalation prevention,
  and more. Configured via `.kube-linter.yaml`.

- `checkov-k8s`
  CIS Kubernetes benchmark and container security checks on manifests in
  `platform/k8s/`. Currently soft-fail while existing manifests are being
  hardened. This posture is separate from Terraform Checkov policy and must not
  be used to justify Terraform soft-fail.

- `checkov-terraform`
  IaC security scan over first-party Terraform in `platform/terraform/`. A
  **blocking gate** under ADR-004-R11. Pre-commit (`.pre-commit-config.yaml`
  `checkov`) and the GitHub Actions `security-iac` job both consume the same
  config at `platform/terraform/.checkov.yaml`; `--soft-fail` is not set on
  either surface. Accepted-risk waivers (Checkov `skip-check` entries in
  `.checkov.yaml` or inline `# checkov:skip=CKV_X:…` comments on individual
  resources) MUST have a matching entry in `docs/adr/exceptions.yaml` with
  `rule_id: ADR-004-R11`, owner, reason (containing the Checkov policy ID),
  `expires_on`, and affected `paths`. `adr_guard.py` rejects expired
  exceptions, forcing owner re-review. Do not create a separate Checkov
  waiver registry; the ADR exceptions registry is the audit trail.

- `k8s-image-registry`
  Verifies that the staged GCP Kubernetes deployment assets still point at
  Artifact Registry (`pkg.dev`), preventing accidental use of public or
  untrusted registries while the GCP workflow and generated assets are being
  reconciled around the Helm cutover.

- `k8s-pss-labels`
  Architecture check ensuring namespace manifests carry Pod Security Standards
  `pod-security.kubernetes.io/enforce` labels. Enforces ADR-006-R1.

- `k8s-deployment-security-context`
  Enforces ADR-006-R2 against two enforcement sources: (1) every YAML
  document under `platform/k8s/gcp/base/` (recursive) whose `kind` is
  `Deployment`, and (2) the rendered output of
  `helm template platform/charts/shifter -f <values>` for each entry
  in `HELM_VALUES_FILES` (`values-gcp-dev.yaml`, `values-gcp-prod.yaml`).
  Per ADR-007 the chart is the authoritative deployment contract;
  base manifests are supporting snapshots. Validating both sources
  catches regressions where a chart template or values file removes
  a required securityContext field even when the base snapshots
  remain compliant. Kind-based filtering, not filename-based, means a
  Deployment shipped under any filename or extension is scanned.
  Multi-document files (`---` separator) and indentless YAML
  sequences are supported.
  Per pod template: `securityContext.seccompProfile.type` must be
  `RuntimeDefault`. Per container AND init container: the *effective*
  context (after pod-level inheritance for `runAsNonRoot`,
  `runAsUser`, `runAsGroup`) must satisfy
  `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` with
  no `capabilities.add`, `readOnlyRootFilesystem: true`,
  `runAsNonRoot: true`, `securityContext.privileged` not `true`, an
  optional container-level `seccompProfile.type` (when set) equal to
  `RuntimeDefault`, and `runAsUser`/`runAsGroup` set to positive
  integers (booleans are rejected since Python treats `bool` as a
  subclass of `int`). Runs in the `ci` level (`--all --level ci`,
  including CI) and in a dedicated pre-commit hook `adr-guard-k8s`
  (separate from `adr-guard-fast`) that triggers on
  `platform/k8s/gcp/base/*.{yaml,yml}` and
  `platform/charts/shifter/` changes. Not in the `fast` level, so
  unrelated `--level fast` invocations and the system-Python
  `adr-guard-fast` hook do not pull in the YAML or helm dependencies.
  **Runtime dependencies:** PyYAML (`pyyaml>=6.0`) and Helm
  (`v3.15.4`). The `adr-conformance` job in
  `.github/workflows/_quality.yml` bootstraps pip via the stdlib
  `ensurepip` module (the self-hosted Amazon Linux runner's system
  Python ships without pip; `actions/setup-python` cannot fetch
  Python 3.12 for the runner's architecture), then installs PyYAML
  via `python3 -m pip install --no-deps --target
  ${RUNNER_TEMP}/py-deps` with `PYTHONPATH=${RUNNER_TEMP}/py-deps`
  on the run step, and Helm via the official `get.helm.sh` release
  tarball extracted to `${RUNNER_TEMP}/helm-bin/` and added to
  `$GITHUB_PATH`. The `--user` site PyPI install of pip itself is
  job-scoped on the self-hosted runner; PyYAML lands under
  `${RUNNER_TEMP}/py-deps` which is ephemeral. The `adr-guard-tests`
  job uses the same ensurepip + PyYAML pattern; the chart-rendering
  test uses a fake helm shim, so CI tests don't need real helm. The `adr-guard-k8s` pre-commit hook
  uses `language: python` with `additional_dependencies:
  pyyaml>=6.0` so PyYAML is provisioned in an isolated pre-commit
  virtualenv; helm is a developer prerequisite shared with the
  existing `helm-lint-shifter-chart` hook. Complements existing
  kube-linter checks (`run-as-non-root`, `no-read-only-root-fs`,
  `privilege-escalation-container`) which cover the subset
  PSS-restricted enforces directly; this check fills the gaps for
  `seccompProfile`, `capabilities.drop`/`add`, container-level
  seccomp overrides, `privileged: true`, pod-level inheritance, and
  initContainer coverage. Implementation note: the validator is
  decomposed into focused helpers (`_check_container_basic_fields`,
  `_check_container_capabilities`, `_check_container_seccomp`,
  `_check_container_identity`, `_resolve_pod_spec`,
  `_resolve_pod_sc`, `_validate_containers_list`, `_scan_targets`,
  `_validate_base_files`, `_validate_chart_renders`) so each piece
  stays under SonarCloud's cognitive-complexity threshold and tests
  can target each clause independently.

- `k8s-network-policy-coverage`
  Enforces ADR-006-R3 against the base manifest snapshots under
  `platform/k8s/gcp/base/` and the rendered Helm chart output for
  each supported values file. Every Shifter namespace discovered in
  those manifests must have a default-deny `NetworkPolicy` with an
  empty pod selector and both `Ingress` and `Egress` policy types.
  The check also rejects broad egress `ipBlock` CIDRs (`0.0.0.0/0`
  and `::/0`) in Shifter NetworkPolicies, forcing policies to use
  explicit GCLB, Google API, private service, and in-cluster service
  ranges. Runs in the `ci` level and shares the Helm-rendered
  validation boundary with `k8s-deployment-security-context`.

- `no-plaintext-secrets-in-tfvars`
  Architecture check that scans `*.tfvars` files committed under
  `platform/terraform/environments/` and flags any line that assigns a
  quoted string literal to a variable whose name ends in `_password`,
  `_passwords`, `_secret`, `_secrets`, `_token`, `_tokens`, `_key`,
  `_keys`, `_credential`, or `_credentials`. Heredoc string literals
  (`name = <<EOF` / `<<-EOF`) are flagged equivalently. Object/array
  assignments to a secret-bearing variable are walked forward to the
  matching brace/bracket and flagged when any string literal appears
  inside (so `db_credentials = { password = "..." }` is caught while
  `db_credentials = { password = var.x }` is allowed). Function-wrapped
  string literals (`db_password = trimspace("...")`,
  `api_token = sensitive("...")`,
  `db_credentials = jsonencode({ password = "..." })`) are caught via
  a same-line RHS scan; multi-line wrapper expressions (jsonencode
  spanning lines, nested function calls across lines) are walked via
  balanced-delimiter matching of `()`/`[]`/`{}` until the expression
  closes, and any inner string literal flags the assignment.
  Var/local/data references and empty strings
  are allowed. Variables whose name ENDS WITH a public-material suffix
  (`public_key`, `public_keys`, `public_cert`, `pub_key`, `pubkey`,
  `authorized_keys`, etc.) are exempted because that material is
  share-only by design; the match is suffix-based so a name like
  `public_key_password` (which has the public-key fragment AND a
  secret suffix) stays flagged. `*.tfvars.example` files are skipped. Both `#` and `//` line comments and `/* ... */`
  block comments are stripped before matching, matching Terraform's
  HCL grammar. Enforces ADR-004-R7. Complements gitleaks, which
  matches high-entropy random strings; this catches low-entropy
  committed credentials gitleaks ignores. Implementation note: the
  check is decomposed into focused helpers (`_collect_tfvars_candidates`,
  `_scan_tfvars_file`, `_flagged_secret_var`, `_block_assignment_has_literal`,
  `_wrapped_rhs_has_literal`, `_lines_have_string_literal`,
  `_find_balanced_close_index`, `_find_block_close_index`, `_balance_scan`,
  `_block_depth_scan`, `_scrub_line`) so each piece stays under SonarCloud's
  cognitive-complexity threshold and tests can target each clause
  independently.

- `mcp-ops-tls-strict`
  Architecture check that fails the build when any file under
  `mcp/ops/` (`.js`, `.mjs`, `.cjs`, excluding `node_modules/`)
  re-introduces `rejectUnauthorized: false` (or `0` / `null`) on a
  TLS configuration. `mcp/ops` connects to RDS Postgres through an
  SSM port forward; `mcp/ops/lib.js::buildPoolConfig` is the single
  call site that builds the pool's TLS config and now preserves
  verification by setting `ssl.servername` to the captured RDS
  endpoint. Comments and string literals are flattened to whitespace
  before matching (mirroring `mcp-no-shell-exec`'s approach) so a
  descriptive doc-string about the prior `rejectUnauthorized: false`
  workaround does not trip the check. Backstops the `buildPoolConfig`
  unit-test invariant on every other JS file in the package. Enforces
  ADR-014-R7.

- `no-tracked-generated-artifacts`
  Architecture check that fails the build when generated or pre-staging
  sensitive artifacts are tracked in source under narrow roots. Two
  artifact families are blocked, each scoped to its own root:
  Terraform plan outputs (`tfplan`, `tfplan.binary`, `plan.out`,
  `*.tfplan`, `*.tfplan.binary`) under
  `platform/terraform/environments/` and
  `platform/terraform/gcp/environments/`; and license / authcode
  bootstrap material (`authcodes`, `*.authcodes`) under
  `temp/bootstrap/`. Enumeration uses `git ls-files` (tracked +
  staged + untracked-but-not-ignored) so ignored ephemeral
  workspace artifacts are intentionally allowed; a synthetic-tree
  test-mode fallback walks the filesystem. The blocked path/name
  set is centralized in `scripts/adr_guard/adr_guard.py` so adding
  another generated filename or environment root is one edit. The
  guardrail fails closed: violations name only the repo-relative
  path and a remediation hint, never echoing plan content, license
  material, or binary payloads. Backstops `.gitignore`, which does
  not retroactively un-track files that were already added (for example,
  through `git add -f`), and complements
  `no-plaintext-secrets-in-tfvars`. Enforces ADR-004-R8.

- `no-populated-secret-env-files`
  Architecture check that fails the build when a tracked
  `*-secrets.env` file under `platform/k8s/` carries a real value on
  any assignment. Comments (lines whose first non-whitespace
  character is `#`), blank lines, empty assignments (`KEY=`), and a
  small **fixed** synthetic-placeholder allowlist
  (`REPLACE_AT_DEPLOY`, `CHANGE_ME`, `PLACEHOLDER`, `EXAMPLE`, plus
  the matching bracketed forms `<replace-at-deploy>`, `<change-me>`,
  `<placeholder>`, `<example>`) are allowed; anything else is
  flagged. The bracket allowlist is an explicit fixed set rather
  than a `<...>` pattern so a committer cannot hide a real credential
  inside angle brackets (for example, `DB_PASSWORD=<attacker-known-password>`).
  The parser splits on the first `=` so non-identifier key shapes
  (`db.password=...`, `api-token=...`, `export DB_PASSWORD=...`) are
  still subject to the value check; inline `# ...` is **not**
  honored as a comment (Kustomize / Docker env_file treats `#` as a
  comment only when it is the first non-whitespace character on a
  line); non-comment, non-blank lines without `=` are flagged as
  malformed. Containment uses `git ls-files` so gitignored local-dev
  files (for example, `platform-runtime-secrets.local.env`) are intentionally
  not scanned; a synthetic-tree test-mode fallback walks the
  filesystem for unit tests. The roots and the synthetic-placeholder
  allowlist are centralized in `scripts/adr_guard/adr_guard.py` so
  adding a future overlay (for example, `gcp-prod`) is automatic and adding
  a new cluster tree is one entry. Failure reporting names the
  repo-relative path and the variable name only; the rejected value
  is never echoed. Real runtime secrets must flow in at deploy time
  from GCP Secret Manager, a gitignored local env file, or a
  deploy-time Kubernetes Secret. Backstops gitleaks for low-entropy
  committed credentials it ignores and prevents reintroduction of
  the failure mode resolved by PR #1207 (issue #1195). Enforces
  ADR-004-R9.

- `rds-pending-modifications`
  Post-`terraform apply` gate in `_shifter-platform.yml`. Reads the portal
  Terraform outputs, then calls `aws rds describe-db-instances` for each
  `*_db_instance_id` output and fails the deploy job if any RDS instance
  still has non-empty `PendingModifiedValues` or non-`in-sync`/`applying`
  `DBParameterGroups[].ParameterApplyStatus`. Catches the failure mode
  documented in `dev/terraform.md` ("RDS Change Application") where a
  successful apply silently queues class/parameter changes for the
  maintenance window. Implementation: `scripts/check_rds_pending_modifications/`,
  with its own uv-managed dev environment, dedicated CI lint+test jobs
  (`check-rds-pending-modifications-lint` / `-tests` in `_quality.yml`),
  and matching pre-commit hooks (ruff + pytest). Same pattern as
  `scripts/check_layer_imports/`.

- `check-tf-kms-secrets-grant`
  Pre-commit hook AND CI step (`.github/workflows/_quality.yml`'s
  `terraform-lint` job) that fails when an IAM role whose attached
  `aws_iam_role_policy` grants `secretsmanager:GetSecretValue` (or
  any wildcard covering it, such as `secretsmanager:*`,
  `secretsmanager:Get*`, or `*`) lacks an attached IAM Statement
  granting `kms:Decrypt` on the portal Secrets Manager CMK. The grant
  must satisfy all three predicates in the SAME Statement: Action
  covers `kms:Decrypt` (action wildcard matching is done with
  `fnmatch`, so `kms:*` and `kms:De*` also satisfy); Resource is
  `var.secrets_manager_kms_key_arn` or `var.secrets_kms_key_arn`
  (both module-input names refer to the same physical portal CMK in
  the environment modules: engine-provisioner and portal/ec2 use
  the first, guacamole uses the second) or `"*"` / `["*"]` (accepted
  when the same statement carries the service condition); Condition
  `StringEquals` or `StringLike` with
  `"kms:ViaService" = "secretsmanager.<region>.amazonaws.com"`. The
  per-statement coexistence check matters because IAM evaluates each
  Statement in isolation; spreading the predicates across separate
  statements does not satisfy a single Decrypt call. Independently,
  any IAM Statement granting `kms:Decrypt` on `Resource="*"` (or
  `["*"]`) must carry a `kms:ViaService` condition pinning to some
  service; unconditioned wildcard `kms:Decrypt` is too broad.
  Existence is gated on `secretsmanager:GetSecretValue` (not file
  layout) so unrelated roles that happen to live in the same file
  are not forced to acquire unnecessary KMS grants. Currently scoped
  via the pre-commit `files:` regex (and the matching CI invocation
  list) to `platform/terraform/modules/engine-provisioner/iam.tf`,
  `platform/terraform/modules/portal/ec2/main.tf`, and
  `platform/terraform/modules/guacamole/iam.tf`; expand both when a
  new module starts reading portal Secrets Manager secrets. The
  check is implemented in
  `scripts/check_tf_kms_secrets_grant/check_tf_kms_secrets_grant.py`
  and tested in
  `scripts/check_tf_kms_secrets_grant/test_check_tf_kms_secrets_grant.py`
  with stdlib `unittest` (mirrors `check_tf_iam_ec2_scope`). The
  test suite itself is run by the `check-tf-checker-tests` pre-commit
  hook and a matching CI step so a parser regression cannot land
  merely because the current live `.tf` files remain in the
  happy-path shape. Enforces ADR-004-R10. Backstops the failure mode
  resolved by #52 where a fresh Secrets Manager CMK rotation left
  several roles without `kms:Decrypt` and ECS task secrets injection
  aborted at startup with `AccessDeniedException: Access to KMS is
  not allowed` (which in turn was silently masked at the portal
  entrypoint by an `export VAR=$(fetch_runtime_secret …)` pattern
  that swallowed the fetch failure; see
  `shifter/shifter_platform/entrypoint-lib.sh` and
  `shifter/shifter_platform/tests/test_entrypoint_lib.sh`).

## Local Usage

Run the fast profile on the full repo:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level fast
```

Run the CI profile:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Useful ecosystem checks:

```bash
cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
actionlint
helm lint platform/charts/shifter -f platform/charts/shifter/values-gcp-dev.yaml
kube-linter lint --config .kube-linter.yaml platform/k8s/
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 platform/k8s/gcp/base/*.yaml
```

Run on specific files:

```bash
python3 scripts/adr_guard/adr_guard.py --files .github/workflows/_quality.yml --level fast
```

Run on staged or modified files:

```bash
python3 scripts/adr_guard/adr_guard.py --changed --level fast
```

## How To Add A Rule

1. Add or update the ADR entry in `docs/adr/index.yaml`.
2. Implement the check in `scripts/adr_guard/adr_guard.py`.
3. Decide where it belongs:
   - fast local gate
   - CI gate
   - Claude post-edit hook
   - agent policy docs
4. If the rule cannot be enforced immediately, add a dated exception to `docs/adr/exceptions.yaml`.

## Exceptions

Use exceptions sparingly. They are for temporary, explicit waivers only.

Required fields:

- `rule_id`
- `owner`
- `reason`
- `expires_on`

Optional narrowing fields:

- `checks`
- `paths`

Expired exceptions fail `adr_guard`, so they cannot linger unnoticed.

## Design Constraints

- Keep the default local gate fast.
- Do not rely on external dependencies for the core ADR guard.
- Prefer explicit exceptions over hidden tolerances.
- Do not make CI architecture checks skippable through the normal test-skip path.
- Keep review friction focused on guardrail files, not on ordinary feature code.
