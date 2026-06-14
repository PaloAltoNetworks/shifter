# ADR Enforcement

This directory holds the machine-readable part of ADR enforcement.

## Files

- `index.yaml`: accepted ADRs and their enforceable rules
- `exceptions.yaml`: time-bounded exceptions to specific rules

The files use JSON syntax with a `.yaml` extension so they stay human-readable while remaining parseable by the standard library.

## Runtime Enforcement

The enforcement entrypoint is:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Optionally pass explicit check names as positional arguments:

```bash
python3 scripts/adr_guard/adr_guard.py --checks layer-imports guardrail-docs --all
```

Current mechanisms:

- `scripts/adr_guard/adr_guard.py`: repo-native policy runner
- `scripts/adr_guard/boundary_mock_baseline.json`: current legacy
  first-party internal mock-patch counts for ADR-019. Counts may shrink
  as tests move to behavioral assertions, but new or increased internal
  patch counts, including baseline allowance increases against the branch
  reference, fail the `boundary-mock-policy` check.
- `.pre-commit-config.yaml`: local fast checks
  - The `Deploy` workflow's always-present `Pre-commit` job runs the
    file-hygiene and secret-scan subset (`trailing-whitespace`,
    `end-of-file-fixer`, YAML/JSON checks, large-file and merge-conflict
    checks, private-key detection, and gitleaks) and feeds `PR Gate`, so
    protected-branch PRs cannot bypass that baseline through path filters.
  - `check-tf-iam-ec2-scope`: local Terraform IAM hardening check that
    keeps engine-provisioner EC2 instance lifecycle actions scoped to
    Shifter-owned, Terraform-managed instances.
  - `check-tf-rds-security`: local Terraform RDS hardening check that
    keeps the portal and Guacamole RDS instances on IAM DB auth and an
    explicit CA certificate identifier.
- `.github/workflows/_quality.yml`: CI architecture gate. Its SonarCloud
  job restores coverage artifacts, sets up Temurin Java 21, and disables
  SonarScanner JRE auto-provisioning so the quality gate does not depend
  on downloading a runtime during analysis. The job uses Node 24-backed
  action majors for checkout, artifact restore, Java setup, and the
  SonarQube Cloud scan so runner deprecation warnings do not mask real
  SonarCloud quality findings.
  - Repository branch protection for `main` and `dev` requires the
    aggregate `PR Gate`, CodeQL, and pull-request title lint with strict
    up-to-date status checks. Admin bypass remains enabled for emergency
    override; normal changes land through PRs.
- `.github/workflows/codeql-analysis.yml`: GitHub CodeQL static analysis
  with the `security-extended` query suite for Python and JavaScript;
  runs on pushes to `main` and `dev`, on pull requests against either
  protected branch, and on a
  weekly schedule. Least-privilege permissions (`contents: read`,
  `security-events: write`, `actions: read`); no `pull_request_target`.
- `.github/workflows/pr-title-lint.yml`: pull-request title validation
  against the conventional-commit shape used by towncrier and the
  release-drafter conventions. PRs to or from the `dev` integration
  branch are exempt; release/environment promotion PRs that do not
  involve `dev` are validated. Allowed types: `security`, `added`, `changed`,
  `deprecated`, `removed`, `fixed`, `feat`, `fix`, `chore`, `docs`,
  `refactor`, `test`, `ci`, `build`, `perf`, `revert`. Subject must
  start with a lowercase letter.
- `.github/workflows/_shifter-engine.yml`: engine image validation and
  deployment. The validate job runs on GitHub-hosted runners because it
  only performs a local Docker build; self-hosted runners are reserved
  for the credentialed build and deploy jobs. The credentialed jobs run
  only on trusted push / manual-dispatch paths, bind a GitHub
  Environment, and update ECS with `repo@sha256` image identity.
- `.github/workflows/deploy.yml`: deploy router. Pull-request events are
  hosted-only (`changes`, pre-commit, Quality, PR Gate) and never route
  AWS/GCP reusable deploy jobs. Reusable deploy jobs receive a
  `github_environment` input distinct from Terraform environment names so
  prod applies can be protected by the `aws-prod` GitHub Environment.
- AWS ECR image identity: first-party AWS ECR repositories are immutable.
  Portal and engine deploy paths push run-scoped tags only as upload
  handles, then consume the resulting ECR digest through SSM/ECS
  `repo@sha256` references. Static Guacamole images are pushed only when
  the version tag is absent, and Terraform resolves that tag to a digest.
- `.github/dependabot.yml`: weekly dependency PRs across every uv,
  npm, github-actions, and pre-commit package root in the repo; every
  block targets the `dev` integration branch.
- `.claude/hooks/adr_guard_hook.py`: Claude post-edit validation
- `AGENTS.md`: Codex repo-local policy. Points at `.ground-control.yaml`
  and `.gc/plan-rules.md` for Ground Control workflow context
  (canonical GitHub repository, requirements, current MCP entrypoints,
  and plan rules); enforcement of ADR rules still lives here.
- `.ground-control.yaml` and `.gc/plan-rules.md`: Ground Control
  workflow configuration and mandatory plan constraints. The
  `github_repo` value is the canonical GitHub target for agent issue,
  PR, CI, and traceability operations.
- `.importlinter`: Python package-level architecture contracts
- `.tflint.hcl`: Terraform lint configuration with `tflint-ruleset-google`
  plugin. The initial rule set is intentionally conservative so it can
  hard-fail on current signal without immediately breaking on unrelated
  legacy Terraform debt.
- `.gitleaks.toml`: secret scanning configuration
- `sonar-project.properties`: SonarCloud project configuration.
  `sonar.html.fileHeader` enforces the ADR-015 file-header convention
  on HTML templates by failing `Web:HeaderCheck` on any template that
  does not begin with the canonical two-line SPDX Django-comment
  header.
- `.kube-linter.yaml`: Kubernetes security and best-practice linting
  configuration (enforces ADR-006 checks)
- `Checkov`: Terraform and Kubernetes IaC security scanning. ADR-004-R11
  makes the Terraform path a blocking gate (pre-commit and CI share
  `platform/terraform/.checkov.yaml`); the Kubernetes path remains
  soft-fail while manifest hardening proceeds as a separate workstream.
  Accepted-risk waivers MUST have an entry in `docs/adr/exceptions.yaml`
  with owner, reason, expiry, affected paths, and the Checkov policy ID.
- `scripts/check_tf_rds_security/check_tf_rds_security.py`: ADR-004-R12
  RDS hardening check for the two first-party AWS RDS instances. It
  requires literal IAM DB auth enablement and an explicit non-empty CA
  certificate identifier, complementing Checkov's RDS policies.
- `scripts/adr_guard/adr_guard.py` `mcp-no-shell-exec` check:
  flags any file under `mcp/` (`.js`, `.mjs`, `.cjs`) that imports
  `child_process` (any shape: named, default, namespace, CommonJS
  destructure, or bare-`require` property access, with or without
  the `node:` prefix) AND uses one of the shell-string call shapes:
  `execSync(...)`, `exec(...)`, an `execSync as <alias>` rename
  used as `<alias>(`, or `spawn`/`spawnSync`/`execFile`/
  `execFileSync` invoked with `{ shell: true }`. String literals
  and comments are flattened to whitespace by a small per-state
  consumer (one helper per state: code / line-comment /
  block-comment / string, preserving newlines), so
  `"https://..."` URLs do not accidentally erase a real call site,
  and so commented-out call sites or strings containing
  `execSync as run` do not trip the check or synthesise fake
  aliases. The check is a cheap pre-commit
  backstop; motivated bypasses such as `const run = cp.execSync;
  run(...)` are outside its reach by design and rely on code
  review. Enforces ADR-010-R1 with no current exceptions —
  `mcp/ngfw/*` migrated to argv-array helpers via the shared
  `mcp/shared/aws-helpers.js` module in #759, alongside the
  original `mcp/ops/*` migration in #763.
- `scripts/adr_guard/adr_guard.py` `boundary-mock-policy` check:
  enforces ADR-019-R1 for Python tests. The checker statically parses
  tracked test files for `patch()` / mock `.patch()` string targets and
  statically resolvable `patch.object(imported_module_or_class, ...)`
  calls. Targets rooted in first-party Python modules are rejected unless
  their `(test file, target)` count is already present in
  `scripts/adr_guard/boundary_mock_baseline.json`. Patches against real
  process/network/cloud/framework transport boundaries, such as
  `subprocess`, `boto3`, HTTP clients, SMTP/socket/SSL, and channel-layer
  transports, remain allowed. The baseline is a ratchet: lower counts
  when legacy mock-coupled tests are rewritten; the check compares the
  committed baseline to the branch reference so authors cannot raise
  counts to land new topology-coupled tests without a dated ADR
  exception. During initial adoption, a base branch without the baseline
  file starts the ratchet from the first merged baseline.

### ADR-019 baseline reduction (#957)

Issue #957 rewrites the remaining non-decomposed mock-coupled test suites
to behavior tests (drive a public entry point; assert outputs / ORM state /
responses) and shrinks `boundary_mock_baseline.json` accordingly. Each group
of suites lands as its own commit that removes the corresponding baseline
entries. Completed so far:

- `mission_control`: core range API, agents, models, and page-view suites
  (`test_range_api*`, `test_agents`, `test_models`, `test_views`,
  `test_engine_models`); engine-service view suites (`test_engine_services`,
  `test_engine_services_lifecycle`) and `test_asset_hierarchy`.

Decomposition-owned suites are out of scope here and land with their own
issues: provisioner (#946), `ctf/**` and `cms/experiments/test_orchestrator*`
(#885, #886, #889-#891), and `cms/scenario_editor/**` (#887, #888).

## Adding A Rule

1. Add or update the ADR in `index.yaml`.
2. Implement or wire a check in `scripts/adr_guard/adr_guard.py`.
3. Document the user-visible mechanism in `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md`.
4. If the rule cannot be enforced yet, add a dated exception in `exceptions.yaml` instead of leaving it implicit.

## Exception Format

Exceptions are explicit and time-bounded:

```json
[
  {
    "rule_id": "ADR-001-R1",
    "owner": "platform",
    "reason": "Temporary migration window",
    "expires_on": "2026-06-30",
    "checks": ["layer-imports"],
    "paths": ["shifter/shifter_platform/ctf/*"]
  }
]
```

Expired exceptions fail `adr_guard`.
