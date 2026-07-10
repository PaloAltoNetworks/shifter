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
  reference, fail the `boundary-mock-policy` check. For example, splitting
  `cms/experiments/orchestrator.py` into a package (#886) moved its test
  suites onto real-model / cloud-boundary assertions and dropped the
  associated `cms.experiments.orchestrator.*` baseline allowances.
- `.pre-commit-config.yaml`: local fast checks
  - The `Deploy` workflow's always-present `Pre-commit` job runs the
    file-hygiene and secret-scan subset (`trailing-whitespace`,
    `end-of-file-fixer`, YAML/JSON checks, large-file and merge-conflict
    checks, private-key detection, and gitleaks) and feeds `PR Gate`, so
    protected-branch PRs cannot bypass that baseline through path filters.
  - `check-tf-iam-ec2-scope`: local Terraform IAM hardening check that
    keeps engine-provisioner EC2 instance lifecycle actions scoped to
    Shifter-owned, Terraform-managed instances.
  - `check-tf-iam-ssm-range-scope`: local Terraform IAM hardening check
    (ADR-004-R17) that stops the shared range guest instance role from
    being granted SSM Parameter Store access wildcarded across the
    environment or range segment (`parameter/shifter/*/range/*`); guards
    the #1178 cross-tenant credential-access fix.
  - `check-tf-iam-ssm-scope`: local Terraform IAM hardening check that
    keeps engine-provisioner SSM Run Command (`ssm:SendCommand`) and
    `ec2:RebootInstances` scoped to Shifter range guest instances via
    resource-tag conditions, so the task role cannot command portal or
    runner instances.
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
  PR, CI, and traceability operations. The optional `routing` block opts
  the repository into per-step `/implement` routing while keeping the
  workflow's gate contract in `.gc/plan-rules.md`.
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
  makes the Terraform path a blocking gate (pre-commit and CI share
  `platform/terraform/.checkov.yaml`); the Kubernetes path remains
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

- `shared` + `risk_register`: the cloud-storage adapter suites
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
  `risk_register/test_audit_services` drives the real audit functions against
  real `AuditLog` rows (asserting the persisted row) instead of patching
  `AuditLog.log`, with the swallow path exercised via a real non-JSON payload
  fault. With these, the `shared` and `risk_register` areas carry no remaining
  ADR-019 baseline entries.

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
