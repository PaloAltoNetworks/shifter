# ADR Enforcement

This directory holds the machine-readable part of ADR enforcement.

ADR-068's [gateway replacement evaluation](../architecture/model-access/gateway-replacement-evaluation-2274.md)
records the clarified #2274 scope, maintained-product comparison, selected
LiteLLM OSS edition, deployment-owned rotation and proposed qualification. Its
registry evidence pointer adds no executable check, exception
or runtime support claim. Broker parking and the supported keyless-direct path
remain unchanged until a separate adoption/cutover decision.

The GCP model-broker IAM guard accepts the cluster-derived
`var.workload_identity_pool` reference for its exact Kubernetes service account
binding. The owning GKE output is resource-backed so fresh bootstrap creates the
pool before bindings; the allowed role, namespace and service account are unchanged.

The GCP `gcp-foundation` bootstrap applies the existing purpose-scoped identity
root before runners, images, and platform infrastructure. Its optional private
image-build VPC has no runtime/runner peering, admits builder and validator
management only through IAP, and remains in the independent foundation state.
The option defaults off for existing deployments. Target project/repository IDs
are checked before writes; targeted bootstrap tests and Terraform validation
cover the first-project ordering (ADR-004 purpose separation; ADR-008 private
operator access).
Native GCE image builds explicitly select `GCP_RANGE_BACKEND=gce` to omit the
GDC-only disk export dependency. Builds retain their immutable image evidence.
Separate candidate qualification is optional and off by default for bootstrap
and deployment; it runs only when an operator dispatches the validation workflow.
Bootstrap requires the configured guest images to exist, not a qualification
verdict. The separate image-promotion workflow retains its evidence requirements.

SDK candidate distributions from pull-request CI include their SHA-256 checksums
and are retained under a revision-specific artifact name for independent adapter
builds. Candidate retention grants no publishing authority. The provisional SDK
publishing scaffold remains restricted to `main` and `adapter-sdk-pypi`, dormant
pending the release-model decision in #2241. Local wheel qualification requires
no SDK publication.

## Files

- `index.yaml`: accepted ADRs and their enforceable rules
- `exceptions.yaml`: time-bounded exceptions to specific rules

The files use JSON syntax with a `.yaml` extension so they stay human-readable while remaining parseable by the standard library.

ADR-058 records the [participant-control realization design](../architecture/raes-participant-control-realization-envelope-1967.md)
under GEN-2005. It is design policy, not a new executable interface contract.
Existing registry, guardrail and import checks validate structure; they do not
prove the runtime guarantees. Mechanism implementation and real-boundary
evidence are required before support is advertised.

The [#1583 preparation preflight](../architecture/raes-in-tenant-artifact-preparation-preflight-1583.md)
applies GEN-002 to ADR-034-R9 and the existing ingestion, authority and worker
boundaries. Its enforcement/evidence matrix distinguishes registry validation
from runtime proof and records the required local/CI routing. It introduces no
new ADR or check. Runtime enforcement now includes exact-image Job admission,
installed IAM/Kubernetes readback, separate worker identities, and fenced
inventory admission. Their behavioral tests complement the repository guards;
the `layer-imports` check scans the separately built preparation worker through
separate candidate-selection and import-extraction helpers while preserving the
ADR-031 shared-RAES-facade restriction. This keeps the worker check
independently maintainable without changing its enforced boundary.
the [operator procedure](../ops/artifact-preparation.md) and
[qualification record](../../shifter/packer/preparation/QUALIFICATION.md) describe
how the deployed boundaries are exercised.
The documentation coverage manifest links the operator guide and technical
design from the feature and platform indexes under GEN-001.

The [#2463 feature-artifact acquisition preflight](../architecture/raes-feature-artifact-acquisition-preflight-2463.md)
records ADR-034-R11 and ADR-034-R12 (platform-owned recipe acquisition of
backend-owned feature artifacts, tracked in an Engine-owned inventory, acquired once before ranges
need them, failing per range) and the matching ADR-034-R4, R6 and R7 and
ADR-032-R3 and R9 amendments (streaming delivery with no fixed payload cap). It
introduces no new check; the rules are design policy until the implementation
lands with its behavioral tests.

The same qualification corrected ADR-008-R7's GCP dynamic-secret conditions.
The closed roles contain only Secret Manager permissions; fully qualified
secret-name prefixes constrain their resource access. The conditions omit the
additional resource-type predicate that rejected real workload calls, and
participant suffix checks extract the parent secret ID from version names.
The Terraform guard still rejects expanded prefixes, workload-secret access,
additional permissions and conditions exceeding Google's complexity limit.
Live provisioner probes cover absent and present secrets, creation, version
publication, readback, deletion and denied platform-secret access. Portal probes
verify both latest and numbered participant versions while rejecting host and
directory credentials.

## Runtime Enforcement

ADR-004-R23 generalizes the GCP CI identity module: purpose-separated build,
validate, promote, release-scan, deploy and destroy identities are rendered from
explicit per-deployment inputs rather than tenant-name branches. The source WIF
guard enforces the generic template with pinned CKV_GCP_125 success and no
Checkov waiver; numeric repository/owner IDs and exact workflow/ref/Environment
tuples are mandatory, and native Terraform tests are registered in the root
validation inventory. One project hosts each deployment, its runner and
automation identities; deploy and destroy retain trusted project-administration
authority. Optional two-project support is deferred. Source-guard regression
tests mutate the real module defaults and outputs to cover all retained role,
permission and output restrictions.

ADR-063 records the [signed CTF receipt binding preflight for #1906](../architecture/ctf-signed-receipt-binding-preflight-1906.md).
It fixes trusted context, protected signer/key registration, lifecycle fencing
and atomic replay evidence while preserving existing validator contracts.
The #1906 source implementation supplies runtime, registration, compatibility,
replay and provider-conformance evidence. Registry and import checks validate
design structure; fresh deployed two-generation evidence remains the #1910
composition gate. This ADR adds no exception.

ADR-011-R9 records the [configurable range lease preflight for #27](../architecture/configurable-range-leases-preflight-27.md).
It binds installation/runtime policy ownership, generation snapshots, extension
admission and reuse of canonical cleanup. Registry checks validate this guidance;
configuration, migration, concurrency, warm-claim and deployment behavior still
require implementation evidence. No runtime check or exception is added here.

Issue #2169's [runtime lease-policy preflight](../architecture/runtime-mission-control-lease-policy-preflight-2169.md)
extends that rule with a CMS-owned tenant/group overlay, deterministic
multi-group resolution, the existing per-generation owner extension, and an
explicit separation from workspace tenancy. The CMS models and resolver,
revision-checked and strict-audited admin API/UI, cold/warm assignment snapshots,
generated contract, SQLite behavior tests, and PostgreSQL concurrency test are
the executable evidence for that rule. Provider paths consume the same persisted
deadline state and contain no lease-policy branch.

Proposed ADR-059, ADR-060 and ADR-061 record the
[#681 model-access design](https://github.com/Brad-Edwards/shifter/blob/dev/docs/architecture/model-access/index.md): a
deployment-owned broker, Engine-owned allocation and mandatory budgets,
and evidence-based revocation/operation. Their registry entries are proposed
design policy. Existing import and registry checks validate structure; they
do not prove the future broker, accounting, cloud isolation or release claims.
Implementation and qualification ownership is explicit in the linked backlog.

Accepted ADR-064 supersedes ADR-059's "no-service-account guest default" for
GCP: range guests receive a default-on, keyless predict-only Vertex model
identity via Workload Identity, mutually exclusive per range with the broker.

Accepted ADR-068 supersedes ADR-067 and the parked broker design in ADR-059,
ADR-060 and ADR-061. The broker is parked and not supported for use, and
keyless-direct (ADR-064) is the only live guest model path. Any future model
access control path is a transparent proxy whose controls are optional, with no
controls by default.

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
- `adr-registry` typed interface contracts: accepted ADRs whose closed shape is
  itself an executable invariant must retain their registered contract kind and
  exact fields. ADR-032 uses `raes-plan-accessor-boundary/v1` to pin the
  serialized-plan ownership split, RAES-free provisioner, fail-closed access,
  canonical naming identity, exact-pin compatibility evidence, and #2082
  delivery boundary. The superseded ADR-054 entry retains its
  `dedicated-customer-authority/v1` shape as historical evidence; ADR-066 is the
  current customer/deployment decision and carries forward only the named
  independent-authority, infrastructure-owner, fail-closed, and evidence rules.
  ADR-055 uses `accessibility-enforcement/v1` to pin the WCAG
  target, incumbent axe/Playwright toolchain, execution cadence, coverage
  inventory, non-growing finding baseline, manual-audit evidence, central
  waiver policy, and scanner security posture. These structural checks do not
  claim that runtime, cloud, browser, or audit evidence has run; those tests
  remain mandatory at their owning boundary.
- `lilrae-identity-boundary`: ADR-024-R6 terminology enforcement. Current
  architecture prose treats LilRAE and APTL as one identity across a rename,
  treats TechVault only as a scenario pack, and requires retired TechVault
  implementation notes to carry a historical boundary while preserving exact
  commands, paths, symbols, image keys, workflow names, release history, and
  external `aptl:*` locators.
- `scripts/adr_guard/boundary_mock_baseline.json`: current legacy
  first-party internal mock-patch counts for ADR-019. Counts may shrink
  as tests move to behavioral assertions, but new or increased internal
  patch counts, including baseline allowance increases against the branch
  reference, fail the `boundary-mock-policy` check. For example, splitting
  `cms/experiments/orchestrator.py` into a package (#886) moved its test
  suites onto real-model / cloud-boundary assertions and dropped the
  associated `cms.experiments.orchestrator.*` baseline allowances.
  Likewise, the CTF god-module decomposition (#683) converted the
  notification and event lifecycle suites to behavioral coverage (real ORM
  plus SMTP/template boundary patches only) and dropped their
  `ctf.services.notification.*` / `ctf.services.event.*` allowances.
- `.pre-commit-config.yaml`: intentionally fast local boundary
  - The `Deploy` workflow's always-present `Pre-commit` job runs the
    file-hygiene and secret-scan subset (`trailing-whitespace`,
    `end-of-file-fixer`, YAML/JSON checks, large-file and merge-conflict
    checks, private-key detection, and gitleaks) and feeds `PR Gate`, so
    protected-branch PRs cannot bypass that baseline through path filters.
  - Local execution retains commit-message policy, file hygiene,
    private-key and gitleaks secret detection, and lightweight language
    formatting/linting. Type checks, architecture and policy guards, IaC
    validation/security scanners, migration checks, and test suites are
    CI-only so a commit does not reproduce the repository-wide pipeline.
- GCP bootstrap and deployment migration Jobs explicitly disable model access
  and clear its catalog path/digest: these database-only Jobs do not mount the
  runtime catalog. Model-broker pods use their application group as `fsGroup`
  so their non-root process can read the projected 0440 fingerprint files.
  The dedicated provisioner-launcher Role grants `list` on pods only in the
  jobs namespace so cancellation can confirm that foreground Job deletion
  removed every pod. It grants no pod mutation, log, or exec access (ADR-006-R4).
  Range-access NetworkPolicies also select the ephemeral post-deploy smoke Job
  so its documented SSH/RDP probe can reach guests; destination CIDRs and ports
  remain identical to the existing portal/guacd access boundary.
- `.github/workflows/_quality.yml`: CI architecture gate. Every quality unit
  it routes is declared in the `.github/quality-path-filters.yaml` contract
  (ADR-004-R24), which the `quality-path-ownership` check reconciles against
  the whole tracked estate. `uat/range-functional-smoke/**` is such a unit
  (`range-functional-smoke-lint` / `-sast` / `-tests`). Its CI jobs cover the
  harness's deterministic layers only: the harness itself drives a deployed
  tenant and a live range, so it is operator-invoked and deliberately has no CI
  execution job and gates no deploy (issue #987).
  Guard implementation modules remain below the CI file-length threshold;
  formatting-only maintenance must preserve that bound without changing the
  guard's exported behavior.
  Its SonarCloud
  job restores coverage artifacts, sets up Temurin Java 21, and disables
  SonarScanner JRE auto-provisioning so the quality gate does not depend
  on downloading a runtime during analysis. The job uses Node 24-backed
  action majors for checkout, artifact restore, Java setup, and the
  SonarQube Cloud scan so runner deprecation warnings do not mask real
  SonarCloud quality findings.
  Manual deployment scans explicitly pass the selected Git branch through
  `sonar.branch.name`: scanner auto-detection does not identify branches for
  `workflow_dispatch`, which otherwise publishes tenant analysis to the Sonar
  project's main branch. Pull-request and push analysis retain auto-detection.
  - Repository branch protection for `main` and `dev` requires the
    aggregate `PR Gate`, CodeQL, and `Lint PR title` with strict
    up-to-date status checks. The title-lint workflow triggers on PRs
    against both branches so the required context reports on each; a
    required context whose workflow cannot trigger for a base branch
    never reports and blocks the merge indefinitely (#1868). Admin
    bypass remains enabled for emergency override; normal changes land
    through PRs.
- `.github/workflows/codeql-analysis.yml`: GitHub CodeQL static analysis
  with the `security-extended` query suite for Python and JavaScript;
  runs on pushes to `main` and `dev`, on pull requests against either
  protected branch, and on a
  weekly schedule. Least-privilege permissions (`contents: read`,
  `security-events: write`, `actions: read`); no `pull_request_target`.
  `.github/codeql/codeql-config.yml` includes synthetic scenario fixtures;
  private training targets are maintained and scanned in their owning repositories.
- `.github/workflows/pr-title-lint.yml`: pull-request title validation
  against the conventional-commit shape Release Please consumes. It runs
  on PRs targeting `dev` and `main`, the two branches whose protection
  requires the `Lint PR title` context. On `dev` the lint guards the
  release signal: squash-merging a feature PR makes the validated title
  the single commit subject Release Please reads once the change reaches
  `main` (ADR-042-R4). On `main` the promotion PR is merged with a merge
  commit and preserves the feature commits, so its title is not a release
  signal; the lint runs there so the required context reports. Allowed
  types: `security`, `added`, `changed`, `deprecated`, `removed`, `fixed`,
  `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`,
  `perf`, `revert`. Subject must start with a lowercase letter.
- `.github/workflows/_shifter-engine.yml`: engine image validation and
  deployment. The provisioner pytest gate and Docker-build validation run
  on GitHub-hosted runners; self-hosted runners are reserved for the
  credentialed build and deploy jobs. The credentialed jobs run only on
  trusted push / manual-dispatch paths, bind a GitHub Environment, require
  the provisioner test gate, and update ECS with `repo@sha256` image
  identity.
- `.github/workflows/deploy.yml`: deploy router. Pull-request events are
  hosted-only (`changes`, pre-commit, Quality, PR Gate) and never route
  AWS/GCP reusable deploy jobs. Reusable deploy jobs receive a
  `github_environment` input distinct from Terraform environment names so
  prod applies can be protected by the `aws-prod` GitHub Environment.
  GCP manual dispatches use the same allowlisted name for the Terraform root
  and protected GitHub Environment (`gcp-dev` or `nazgul`), preserving the
  environment-bound deploy identity. The router separately selects the
  purpose-scoped `gcp-release-scan-*` Environment, and the reusable workflow
  accepts inventory-published `GCP_WIF_PROVIDER` / `GCP_SERVICE_ACCOUNT`
  variables while retaining the legacy secret names as a compatibility path.
  Deploy preflight checks stop at the deploy Environment boundary; the scanner
  job validates its own identity only after entering its purpose Environment.
  The deploy router passes `skip_tests: false` literally into
  `_quality.yml`; commit-message flags such as `[skip tests]` are not
  accepted on protected branches. Inside `_quality.yml`, `skip_tests` may
  only skip unit-test, coverage, SonarCloud, and stack-smoke jobs; lint,
  ADR conformance, IaC security, and other architecture gates always run
  (ADR-003-R2, #760).
- AWS ECR image identity: first-party AWS ECR repositories are immutable.
  Portal and engine deploy paths push run-scoped tags only as upload
  handles, then consume the resulting ECR digest through SSM/ECS
  `repo@sha256` references. Static Guacamole images are pushed only when
  the version tag is absent, and Terraform resolves that tag to a digest.
- `.github/dependabot.yml`: weekly dependency PRs across every uv (including
  the standalone `shifter_client` transport),
  npm, github-actions, and pre-commit package root in the repo; every
  block targets the `dev` integration branch. One block per package
  root, and a block's directory must name a root that actually holds a
  manifest; Dependabot silently ignores a block whose directory does
  not exist, leaving that root unwatched. The SPA
  (`shifter/shifter_platform/frontend`) is a separate npm root from
  `shifter/shifter_platform` and carries its own block; the latter does
  not reach it (#1880).
- `.claude/hooks/adr_guard_hook.py`: Claude post-edit validation
- `AGENTS.md`: Codex repo-local policy. Points at `.ground-control.yaml`
  and `.gc/plan-rules.md` for Ground Control workflow context
  (canonical GitHub repository, requirements, current MCP entrypoints,
  and plan rules); enforcement of ADR rules still lives here.
- `.ground-control.yaml` and `.gc/plan-rules.md`: Ground Control
  workflow configuration and mandatory plan constraints. The
  `github_repo` value is the canonical GitHub target for agent issue,
  PR, CI, and traceability operations. The optional `routing` block opts
  the repository into per-step `/implement` routing while keeping the
  workflow's gate contract in `.gc/plan-rules.md`. The configured
  completion boundary is the root `make test` target; `make policy`
  composes the existing ADR, import, diff, and changed-document checks
  required by the synchronized pre-PR gate. The `routing` block accepts
  only `enabled`, `default_provider`, and `stages`; a stale
  `default_fallback` key, valid when the block was first written and
  later removed upstream without a migration, was dropped in #1581. See
  `docs/technical/dev/adr-enforcement.md` for how whole-file validation
  makes an unrecognized key fail closed. The retired
  `workflow.test_quality_review` block was removed in #2122 because the
  current Ground Control schema no longer accepts the separate reviewer.
  The configured pre-push review, pre-commit, CI, and SonarCloud gates
  remain in force.
- `.mcp.json`: the repository MCP launch contract runs the released `grndctl`
  package (`grndctl mcp`) instead of a mutable source checkout. This keeps the
  server version aligned with the installed workflow skills while preserving
  the repository's other MCP servers.
- `.github/workflows/ground-control-phase-e.yml`: the package-generated,
  version-pinned Ground Control finalizer. After a delivery PR merges to
  `main` or `dev`, it replays the trusted Phase D handoff through
  `grndctl finalize-merged-pr`; it performs no implementation verification and
  has only read permissions plus the issue write needed for the final report
  and issue close.
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
  header. Bootstrap-specific `sonar.issue.ignore.multicriteria`
  entries are limited to `scripts/bootstrap/**` and cover
  subprocess argv false positives, fixed infrastructure CIDR defaults,
  generic module/control-flow size rules, and scanner-consumed inline
  pragmas; bootstrap still runs Ruff, pytest+coverage, Bandit, and ADR
  guard in local and CI quality gates.
- `.kube-linter.yaml`: Kubernetes security and best-practice linting
  configuration (enforces ADR-006 checks)
- `Checkov`: Terraform and Kubernetes IaC security scanning. ADR-004-R11
  makes the Terraform CI path a blocking gate using
  `platform/terraform/.checkov.yaml`; the Kubernetes path remains
  soft-fail while manifest hardening proceeds as a separate workstream.
  Accepted-risk waivers MUST have an entry in `docs/adr/exceptions.yaml`
  with owner, reason, expiry, affected paths, and the Checkov policy ID.
- `scripts/check_tf_rds_security/check_tf_rds_security.py`: ADR-004-R12
  RDS hardening check for the two first-party AWS RDS instances. It
  requires literal IAM DB auth enablement and an explicit non-empty CA
  certificate identifier, complementing Checkov's RDS policies.
- `scripts/check_tf_iam_ssm_range_scope/check_tf_iam_ssm_range_scope.py`:
  ADR-004-R17 IAM hardening check that rejects SSM Parameter Store grants
  on the shared range guest instance role whose Resource wildcards across
  the environment or range segment (`parameter/shifter/*/range/*` or an
  unbounded `parameter/shifter/<env>/range/*`). The provisioner
  orchestrator role's env-scoped grant is not inspected. Guards the #1178
  cross-tenant credential-access fix.
- ADR-004-R21's legacy guest-role issuer and dedicated checker have been removed.
  ADR-059's broker mediates model access where enforcement is required; ADR-064
  adds a default-on, keyless predict-only guest model identity as the baseline.
  The general IAM checks remain.
- `scripts/check_tf_iam_role_naming/check_tf_iam_role_naming.py` and
  `scripts/check_tf_iam_elb_scope/check_tf_iam_elb_scope.py`: ADR-004-R25
  request-owned VPN gateway hardening. The checks pin the exact gateway role
  and instance-profile permissions-boundary carve-outs and tamper deny, keep
  GWLB and `shifter-vpn-*` NLB action/resource namespaces separate, require
  parent-NLB authorization and ownership resource tags for `CreateListener`,
  and require the runtime VPN listener to send `local.common_tags` at creation.
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
  review. Enforces ADR-010-R1 with no current exceptions—
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

- `scripts/bootstrap`: issue #687 mechanically split the legacy
  `test_deploy.py` suite into behavior-focused files. The ADR-019 baseline
  entries were redistributed to the new paths with a dated exception because
  the ratchet keys on `(test file, target)`; after porting the latest dev
  GCP/GDC tests, the aggregate bootstrap allowance shrank from 215 to 214 and
  the deleted `walkthrough_git_commit` seam was not carried forward.

- `mission_control`: core range API, agents, models, and page-view suites
  (`test_range_api*`, `test_agents`, `test_models`, `test_views`,
  `test_engine_models`); engine-service view suites (`test_engine_services`,
  `test_engine_services_lifecycle`) and `test_asset_hierarchy`; the SNS->
  WebSocket handler suite (`test_handlers`), driven against the real in-memory
  Channels layer; the agent-upload and experiment-script view suites
  (`test_views_uploads`, `test_views_files`), with S3 mocked only at the `boto3`
  boundary and the validation / error-sanitization / authorization paths driven
  for real; the Guacamole token-readiness retry suite
  (`test_guacamole_readiness`), mocking the HTTP exchange at the real `urllib`
  boundary and recording backoff sleeps via `monkeypatch` instead of a
  first-party `time.sleep` patch.
- `engine`: range-lifecycle service suites (`engine/services/test_create_range`,
  `test_cancel_range`, `test_destroy_range`, `test_pause_range`,
  `test_resume_range`), driven against real `Range`/`Request` rows. ECS is a
  no-op for create/destroy; pause/resume require a successful dispatch, so they
  configure ECS via `override_settings` and mock the AWS task runner at the
  `boto3` boundary. Range-query suites (`test_get_range_status`,
  `test_get_instance_ips_by_uuid`) read real rows' `provisioned_instances`. The
  SNS event handler suite (`engine/test_handlers`) drives the handlers against
  real `Range` rows and asserts the persisted status/timestamp updates + audit
  row. The ECS task-dispatch suites (`engine/ecs/**`) drive the real
  `shared.cloud` task runner with AWS configured via settings and the ECS client
  mocked only at the `boto3` boundary, asserting the dispatch contract reaching
  `boto3` (cluster / task definition / container / command line / network
  config); the local-provisioner routing is driven over the real
  `subprocess.Popen` boundary, and the GCP path drives the real config/env
  units (`_get_engine_task_config`, `_get_gcp_provisioner_env_overrides`) rather
  than mocking the runner factory. The SSH/secrets/NGFW service suites
  (`engine/services/test_secrets`, `test_get_rdp_connection_info`,
  `test_connect_ngfw_terminal`, `test_destroy_ngfw`, `test_ngfw_lifecycle`, and
  `engine/ssh/test_ssh_connection`) drive real `Request`/`Instance`/`Range` rows
  with the SSH key/RDP secret fetched over the `boto3` Secrets Manager boundary,
  the NGFW teardown/lifecycle dispatched over the real `engine.ecs` boto3 path,
  and the SSH transport mocked at the third-party `asyncssh` library boundary.
  `test_get_ssh_connection_info` and `test_connect_terminal` are also driven
  against a real active `Range`: the underlying service previously resolved the
  range with a `provisioned_instances__contains` JSON lookup that the SQLite test
  backend cannot execute (`NotSupportedError`); it now resolves the user's active
  range via `Range.get_active_for_user` (consistent with
  `get_rdp_connection_info`), removing the non-portable query. With these, the
  engine group carries no remaining ADR-019 baseline entries.

- `cms` (core): range-service suites (`test_services_range`,
  `test_services_range_destroy_cancel`, `test_services_range_pause_resume`,
  `test_services_range_lifecycle`). These drive the real CMS services through the
  full hydrate -> engine -> persist stack against a real DB: a custom DB
  `Scenario` hydrates a windows-agent range, engine ECS is unconfigured so
  create/destroy/cancel are no-ops, and pause/resume configure ECS with the AWS
  task runner mocked at the `boto3` boundary. Assertions are on persisted cms
  `RangeInstance` / engine `Range` state, `AuditLog` rows, and the returned
  `RangeContext`. The event-handler suites (`test_handlers`, `test_handlers_ngfw`)
  drive `process_event` / `process_range_event` / `process_ngfw_event` against
  real `RangeInstance`/`Request`/`Instance`/`App` rows and assert the persisted
  status (and `App.data.serial_number`) updates; the range handler's CTF bridge
  is verified by connecting a real receiver to the `range_status_changed` signal,
  and dispatcher routing is verified through each sub-handler's real effect
  Legacy experiment routing was removed by ADR-027 / issue #1195, so dispatcher
  routing no longer includes the deleted experiments handler.
  The asset-service and S3-helper suites (`test_assets`, `assets/test_s3`) drive
  the real `cms.assets.services` (create/delete/storage) against real
  `AgentConfig`/`OperatingSystem`/`AuditLog` rows and the real `cms.assets.s3`
  helper through the `shared.cloud` AWS adapter, mocked only at the `boto3` S3
  client boundary (with `AWS_S3_BUCKET_NAME` set so the real not-configured guard
  is not tripped); the delete fail-fast path is driven with a `boto3` `ClientError`
  and asserts no soft-delete occurs. The presigned-upload lifecycle suites
  (`test_services_upload`, `test_services_upload_cancel`,
  `test_services_upload_complete`) drive `initiate_upload` / `cancel_upload` /
  `complete_upload` against a real user, real quota/extension validation, and a
  real signed upload token (round-tripped through `generate_upload_token` /
  `verify_upload_token` rather than patched): `initiate_upload` asserts the issued
  token's verified payload; `complete_upload` runs the full verify -> header-inspect
  -> tag -> `create_agent` stack and asserts the persisted `AgentConfig`/`AuditLog`,
  the magic-byte-mismatch delete-and-abort, and that rejection logs do not leak
  header bytes; S3 (presign / head / range-GET header read / tag / delete) is
  mocked only at the `boto3` boundary. The `cms.services` suites
  (`test_services`, `test_services_storage`, `test_services_agents`,
  `test_services_scenarios`, `test_services_ngfws`) drive the agent / storage /
  range-projection / scenario / NGFW service entrypoints against real rows: the
  range-projection IP overlay reads a real engine `Range`'s
  `provisioned_instances` through `engine.services.get_instance_ips_by_uuid`;
  the scenario services drive the real registry (built-in templates + DB customs);
  the NGFW services drive real `Credential` / `Request` / `Instance` / `App` rows
  and the seeded `panw-ngfw` catalog + `deployment_profile` / `scm` credential
  types, with `create_ngfw` running the full resolve -> provision -> hydrate ->
  dispatch stack (engine NGFW provisioning is a no-op under unconfigured ECS) and
  the engine-error path driven by a real engine NGFW instance with an attached
  range. Impossible-state defensive tests (the ORM returning `None` / a
  wrong-typed object / a list of dicts) and generic unexpected-exception re-raise
  tests are dropped per the boundary-mock-policy intent (ADR-019). The model and
  scenario-hydrator suites (`test_models`, `test_credentials`,
  `test_models_agent_config`, `test_models_asset`, `test_models_operating_system`,
  `test_models_range_instance`, `test_models_subnet`, `test_scenario_hydrator`)
  drive real rows for the ORM-dependent cases—Credential/CredentialType
  create/uniqueness/cascade/PROTECT, `active_for_user` soft-delete filtering,
  `RangeInstance` create/query/`select_related`, `OperatingSystem.get_for_extension`,
  and the `Subnet` terminal soft-delete invariant—keeping the field-inspection
  and in-memory property tests as-is. `test_scenario_hydrator` drives the real
  `hydrate_scenario` against real DB `Scenario` rows (loaded through the real
  registry) and real `AgentConfig` rows, exercising `from_agent` OS resolution and
  agent embedding. With these the `cms` core area carries no remaining ADR-019
  baseline entries.

- `cms/experiments`: ADR-027 / issue #1195 removed the legacy experiments app,
  its script-upload surface, websocket/event handlers, bridge tests, and
  ADR-019 baseline allowances. New experiment capability must arrive through a
  new accepted design rather than restoring these deleted suites or their
  first-party patch baselines.

- `management`: the service suite (`test_services`) drives `log_activity` /
  `get_user_profile` / `mark_user_deleted` / `create_user_profile` /
  `save_user_profile` / `update_cognito_sub` against real `UserProfile` /
  `ActivityLog` / `AuditLog` rows (accounting for the `post_save` signal that
  auto-provisions a profile), with the real duplicate-profile `IntegrityError`
  exercised directly and generic fault-injection tests dropped; `test_apps`
  verifies the profile signal wiring through its real effect (creating/saving a
  user provisions a profile) rather than asserting `post_save.connect` shapes;
  and `test_check_model_fks` drives the real management command against the real
  (clean) model graph and exercises the violation-count path via the real
  `compute_stats`. `management` was added to the `enable_log_propagation` fixture
  so its service logs are observable by `caplog`.

- `shared`: the cloud-storage adapter suites
  (`shared/cloud/test_aws_storage`, `test_gcp_storage`) drive the real
  `AWSObjectStorage` / `GCPObjectStorage` (including their real `_get_client`
  region/endpoint/client resolution) and mock only the SDK boundary—
  `boto3.client` and `google.cloud.storage.Client` respectively—rather than
  patching the first-party `_get_client`. `shared/test_email` drives the real
  `send_email` through the real thread pool and asserts the locmem outbox
  instead of patching `shared.email.send_email`. `shared/test_notifications`
  drives the real in-process `InMemoryChannelLayer` (a real channel is
  subscribed to the user/topic group and the dispatched event is received off
  the layer) instead of patching `get_channel_layer` / `async_to_sync`; the
  `IntegrityError` race-fallback test is dropped because the unique constraint
  exactly matches the `get_or_create` lookup, so the fallback is reachable only
  via a genuine multi-connection race or by mocking the first-party manager.
  `shared/test_audit_store` drives the real audit functions against
  real `AuditLog` rows (asserting the persisted row) instead of patching
  `AuditLog.log`, with the swallow path exercised via a real non-JSON payload
  fault. With these, the `shared` area carries no remaining ADR-019 baseline
  entries.

- `mission_control` Guacamole connection-URL endpoints
  (`test_guacamole_ssh`, `test_api_instance_ssh_url`, `test_api_ngfw_ssh_url`,
  `test_views_guacamole`): drive the real views → real `engine.services`
  (`get_ssh_connection_info` / `connect_ngfw_terminal` /
  `get_rdp_connection_info`, against real READY `Range` rows and real NGFW
  `Instance` / `Request` rows) → real `mission_control.guacamole` URL builders
  (real AES/HMAC sign-and-encrypt). Only the cloud/network boundaries are
  mocked: the boto3 Secrets Manager client that yields the SSH/RDP secret and
  the urllib Guacamole `/api/tokens` POST. Assertions read the returned URL and
  the decrypted payload that was actually POSTed, instead of patching
  `engine.services.*` / `mission_control.guacamole.*` / the bootstrap enqueue.
  Generic fault-injection tests are replaced with real-boundary equivalents
  (a Secrets Manager `ClientError` drives the 500 path; an invalid signing
  secret drives the URL-build failure; a real exhausted bootstrap-worker
  semaphore drives the 503); the unreachable range-SSH `PermissionError`
  defensive branch is dropped. Shared cloud/Guacamole boundary helpers live in
  `tests/mission_control/conftest.py`.

- `mission_control` NGFW management pages (`test_views_ngfw`,
  `test_ngfw_detail`): drive the real list/wizard/deprovision/detail HTML views
  and the create/list/destroy JSON APIs → real `cms.services` NGFW entrypoints
  (`list_ngfws` / `get_ngfw` / `create_ngfw` / `destroy_ngfw` /
  `list_credentials`) against real `App` / `Instance` / `Request` / `Credential`
  rows → the real templates and JSON, instead of patching the cms service
  functions and `render`. Engine NGFW provisioning is a no-op (ECS unconfigured),
  so no cloud mock is needed. NGFW App/credential factories live in
  `tests/mission_control/conftest.py`. Driving the real `ngfw_detail` render
  surfaced (and this PR fixes) a pre-existing product bug the old
  mocked-`render` test hid: `ngfw_detail` passed `int(cms NGFWAppContext
  .instance_id)` (a CMS Instance UUID coerced to a 128-bit int) to
  `get_ranges_for_ngfw`, which filters the engine `Range.ngfw_instance` (a
  64-bit int FK to the engine NGFW Instance)—different id spaces, so the
  detail page 500'd on SQLite / showed no linked ranges on Postgres. The view
  now correlates via the shared provisioning `request_id` (exposed on
  `NGFWAppContext`), and `get_ranges_for_ngfw` resolves the engine NGFW Instance
  from that request_id and returns the `LinkedRangeContext` projection the
  template already expects. `test_ngfw_detail` asserts the real linked-ranges
  render end to end.

- `mission_control` consumers + misc (`test_context_processors`, `test_oidc`,
  `test_health`, `consumers/test_range_status_consumer`,
  `consumers/test_ssh_consumer`, `consumers/test_ssh_consumer_capacity`): the
  `active_range` context processor is driven against real `RangeInstance` rows
  (the stored `range_spec` controls the projected instances, real group
  membership decides `is_ctf_participant_only`, and runtime private IPs come
  from a real linked engine `Range`) instead of patching `get_active_range` /
  `is_ctf_participant_only` / `logger`. `test_oidc` drives the real
  `ShifterOIDCBackend.create_user` / `update_user` / `_update_cognito_sub`
  (real mozilla base + real `update_cognito_sub` / `audit_auth_event`),
  asserting persisted flags / `UserProfile` / `AuditLog`. `test_health` drives
  the real channel-layer probe over the in-process `InMemoryChannelLayer` and
  the real missing-default-layer path (third-party `health_check` backends are
  still patched for the DB/cache failure cases—those are real boundaries).
  The WebSocket consumers drive the real `connect_terminal` /
  `get_range_by_request_id` / `audit_session_event` against real READY `Range`
  rows (`@pytest.mark.django_db(transaction=True)` so `sync_to_async` sees the
  committed rows), mocking only the boto3 Secrets Manager and the asyncssh
  transport boundary; the range-lookup connect paths are additionally covered
  real by `tests/integration/engine/test_consumers_integration.py` and
  `tests/integration/asgi/test_terminal_ws.py`. Generic/impossible-state and
  incidental-logging tests are dropped per the policy intent.

- config / documentation / integration / views misc (`config/test_logout`,
  `documentation/test_views`, `integration/engine/test_range_lifecycle`,
  `views/test_launch_range_scenarios`): `test_logout` drives the real
  `logout_view` through the test Client with a real session (the real Django
  `logout` flushes it) instead of patching `config.views.logout`.
  `documentation/test_views` drives the real `doc_index` render and asserts the
  captured `response.context` (nav_tree / active_nav) instead of patching
  `documentation.views.render`. `test_range_lifecycle` drives the real
  `get_rdp_connection_info` → `get_rdp_password` over the boto3 Secrets Manager
  boundary instead of patching `engine.services.get_rdp_password`.
  `test_launch_range_scenarios` drives the real `mission_control:launch_range`
  endpoint → real `cms_list_scenarios` / `cms_get_agent` / `cms_create_range`
  against a real custom hydratable `Scenario` + a real Windows `AgentConfig`
  (engine provisioning is a no-op, so the range stays `provisioning`), with the
  real-boundary CMSError paths (a second launch hits "already have an active
  range"; an unknown agent classifies to a safe message) and `caplog` for the
  success/failure log assertions, instead of patching `cms_create_range` /
  `cms_list_scenarios` / `cms_get_agent` / `logger`.

### Refactor-survival demonstration (#957)

The point of the boundary-mock policy is that behavior tests survive refactors
that mock-coupled tests would not. To demonstrate this concretely, the
`generate_username` Django-username validator was moved out of the OIDC backend
module (`config/oidc.py`) into its own `config/username.py`, and the single
topology reference (`OIDC_USERNAME_ALGO = "config.username.generate_username"`)
was updated. The `tests/mission_control/test_oidc.py` `ShifterOIDCBackend`
behavior tests—which exercise `generate_username` only through the real OIDC
`create_user` / `update_user` login flow (via `OIDC_USERNAME_ALGO`), never naming
the function's location—pass **unchanged** across the move. Only the function's
own direct unit tests (`TestGenerateUsername`) updated their import to follow it.
A mock-coupled test that had patched `config.oidc.generate_username` would have
broken on the move; the behavior tests did not.

Decomposition-owned suites are out of scope here and land with their own
issues: provisioner (#946), `ctf/**` (#885, #886, #889-#891), and
`cms/scenario_editor/**` (#887, #888). The legacy `cms/experiments`
decomposition path was removed by ADR-027 / issue #1195.

### ADR-019 baseline reduction (#885)

Splitting `ctf/views.py` into the `ctf/views/` package (#885, `python:S104`)
removed every first-party `ctf.views.*` patch the CTF view tests carried. The
view tests that drove role/render/participant resolution by patching
`ctf.views.get_user_role`, `ctf.views.render`, `ctf.views._get_active_participant`,
`ctf.views._get_participant_for_challenge`, and `ctf.views._resolve_bracket_filter`
were rewritten to behavior tests: organizers are driven through real group
membership (so the real `get_user_role` resolves), and the render / participant
/ bracket paths run for real under `@pytest.mark.django_db` with the conftest
user/event/participant fixtures (services mocked only at their already-tracked
boundary). The corresponding 11 `ctf.views.*` entries were removed from
`scripts/adr_guard/boundary_mock_baseline.json` (ratchet shrink).

## Adding A Rule

1. Add or update the ADR in `index.yaml`.
2. Implement or wire a check in `scripts/adr_guard/adr_guard.py`.
3. Document the user-visible mechanism in `docs/technical/dev/adr-enforcement.md`.
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

Expired exceptions fail `adr_guard`, and they also stop suppressing: once
`expires_on` has passed, the entry no longer covers its violations and those
findings resurface on their own. An entry whose `expires_on` is missing or
unparseable never suppresses anything, so a malformed date cannot buy
open-ended cover. `expires_on` is inclusive: the exception is live through that
date and dead the day after.

Broker activation now requires an enabled v3 accounting catalog, an exact provider
inventory, separate broker/provisioner workload identities and a versioned HMAC
Secret reference. Installer projection and real Helm-render tests enforce these
bindings. GCP deployment cleanup also removes the narrowly scoped provisioner-to-
control enrollment egress policy. Standby infrastructure renders zero broker and
control replicas until model access is enabled; no executable deployment or cloud
qualification is implied by rendering. See [model access operations](../ops/model-access.md).

M05 additionally binds active GCP control identities to the distinct numeric
service-account IDs read back from Terraform. Installer, Helm schema/templates
and startup all reject absent or overlapping IDs. Broker isolation is checked
by the existing import contract; real TLS, PostgreSQL races, bounded worker/DB
waits and content-sentinel tests lock the runtime boundary. No architectural
exception or CI relaxation is introduced. See the
[implemented broker contract](../architecture/model-access/broker-runtime.md).

The GCP workflow reads a reviewed per-environment model overlay when present,
verifies deploy-owned TLS resources, and projects the sealed catalog into every
runtime ConfigMap consumer. `platform/deploy/gcp/**` is owned by the GCP scripts
lint, SAST, and test quality unit; a template change therefore cannot bypass
the production-path quality matrix.

Guest model enrollment is projected as allocation/role/target identities alongside
an immutable operation input. The tenant-approved adapter manifest declares role
bindings; only Engine's admitted allocations can populate them. A trusted SSH
stdin channel delivers a one-use token after realization, and Linux tmpfs holds
the guest's rotating broker tokens. GCP provisioner admission now permits three
non-secret enrollment coordinate/trust values only when they exactly match the
runtime ConfigMap. The broker renderer supplies those values for both Helm and
Actions. Real TLS helper tests cover trust failure, redirect refusal, state-file
permissions and serialized refresh. AWS SSM does not qualify as secret delivery.

The external-runtime test-quality repair makes toolchain-dependent checks
selectable with the `integration` marker while retaining them in default CI runs.
The bootstrap/GCP script jobs explicitly provision their rendering tools. Chart
security checks assert the default-deny policy bodies for every provider profile,
including the isolated plugin namespace. See [testing guidance](../dev/testing.md).

The chart enrollment schema admits the generic cloud endpoint projection: a
GCP guest VIP or AWS guest endpoint CIDRs alongside the shared TLS enrollment
settings. Its closed property list continues to reject undeclared settings.
Real Helm schema tests cover both cloud contracts.

Development-branch integration preserves address-keyed subnet reservations and
pre-mutation cleanup across the external runtime seam. Model enrollment now
activates pending grants only on one-use token exchange, and re-enrollment
revokes old request authority. Accounting retains complete billing evidence,
hard request deadlines and owner-first locks alongside request reconciliation.

The latest hook cleanup retains fast syntax/format checks, pure-Python IAM and
network scoping guards, and secret/identifier hygiene. Full tests, type checks
and external infrastructure scanners remain in CI. Retired scenario-role checks
and private-content exclusions are not restored by development-branch merges.

The AWS model-broker module is included in the Terraform validation inventory
with active contract tests. Broker and control listeners bind the explicit
private pod IPv4 address supplied by the Downward API, with TLS, workload identity
and NetworkPolicy enforcing the service boundary. EC2 secret categories derive
from a closed authentication-method set. Secret scanning remains enabled without
a suppression for these category identifiers.

The isolated GKE plugin pool uses the version-6 Google beta provider required
for sandbox configuration. Module contract tests pin the same provider family
as both deployment roots, so a newer module-only schema cannot mask an invalid
deployment configuration. Native range power capabilities are refused before
legacy worker dispatch because native realization has a separate member inventory.

The runtime security annotations also cover Sonar's wildcard-listener and shared
temporary-directory findings: broker/control sockets are private Kubernetes
Services with mandatory TLS, workload authentication and enforced NetworkPolicy;
the plugin `/tmp` is a per-pod, size-bounded memory volume, with host mounts denied.
These scoped annotations retain those deployment controls and their contract tests.

The GCP image validator's custom role includes instance metadata and label writes
required when creating its disposable candidate and scanner VMs. SSH keys stay
instance-local with project keys blocked; both VMs retain no service account,
no OAuth scopes, and no external IP. This does not grant project metadata writes
or service-account attachment permissions.
Instance listing and Compute project readback support the existing gcloud
IAP/SSH/SCP transport; the role retains no project metadata write permission.
The runner starts its IAP listener without a one-shot guest connection check;
bounded SSH/LDAP probes still gate validation through first boot and reboot.
An exited tunnel process fails promptly instead of consuming the boot timeout.
