# Bootstrap Deployment Decomposition Preflight (#687)

Status: pre-implementation guidance

Date: 2026-06-30

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/687>

This issue is requirement-free. The GitHub issue title, body, and acceptance
criteria are the shipping contract. This note records repo-wide guardrails for
the refactor and is not an implementation plan.

## Scope Boundary

Issue #687 is a structure-preserving refactor of the bootstrap deployment CLI
and its tests. The intended outcome is focused modules and behavior-scoped test
files, not new deployment behavior.

In scope:

- Keep `scripts/bootstrap/deploy.py` as the executable entrypoint and CLI
  compatibility facade.
- Move unrelated responsibilities out of the facade by operation boundary:
  terminal UX/subprocess support, AWS account bootstrap, backend config and
  GitHub secret walkthroughs, AWS Terraform deploy orchestration, GDC cluster
  setup, GCP control-plane/Helm rendering, runner setup, and CLI wiring.
- Split `scripts/bootstrap/tests/test_deploy.py` by behavior while preserving
  equivalent coverage and side-effect isolation.
- Reduce functions over 100 LOC unless the remaining function has one bounded,
  documented responsibility.

Out of scope unless a regression is discovered while preserving behavior:

- Changing command names, flags, defaults, prompts, dry-run semantics, or the
  required deploy sequence.
- Changing cloud resources, IAM permissions, Terraform state layout, Helm chart
  contracts, GitHub workflow routing, or GCP/GDC runtime posture.
- Introducing a generic deploy framework, provider abstraction, schema
  registry, exception hierarchy, persistence model, or logging framework.

## Architecture Decisions

- Split by operation boundary, not by a new "cloud abstraction" layer. The AWS
  bootstrap path, AWS Terraform path, GDC cluster substrate, and GCP control
  plane have different contracts and should stay explicit.
- The executable `deploy.py` remains the user-facing compatibility boundary.
  It may delegate, but existing invocations such as
  `./scripts/bootstrap/deploy.py bootstrap|terraform|full|gdc-bootstrap ...`
  must continue to work.
- The terminal UX and subprocess gateway are cross-cutting bootstrap support.
  If moved, keep `Colors`, `info`/`warn`/`error`, prompt helpers,
  `_validate_argv`, `_redact_argv_for_log`, and `run_cmd` together behind one
  small support module so callers do not fork prompt or command safety rules.
- Move validators with the contract they protect. Do not duplicate GCP control
  plane security validators, image-tag validation, Terraform-output shape
  checks, backend bucket/env validators, or argv redaction in each new module.
- Preserve the current dependency direction. Existing `runner.py` imports UX
  helpers from `deploy.py`; after decomposition, helper imports should target a
  stable bootstrap support module rather than a facade that imports the world.
- Tests should mirror public behavior and real boundaries. Mock process/cloud
  boundaries such as `subprocess`, `urllib`, `boto3`/`gcloud`/`aws` CLI calls,
  and filesystem temp dirs; do not grow first-party implementation patching
  beyond the ADR-019 baseline.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #687 |
| --- | --- | --- |
| CLI contract | `scripts/bootstrap/deploy.py::main`, `scripts/bootstrap/README.md`, `AWS_ENVIRONMENTS` | Keep command names, args, choices, help intent, dry-run behavior, and entrypoint path stable. |
| Terminal UX and subprocess safety | `Colors`, `confirm`, `confirm_or_manual`, `wait_for_user`, `prompt_required_value`, `_validate_argv`, `_redact_argv_for_log`, `run_cmd` | One bootstrap command gateway. All external commands stay argv-list based; no `shell=True` or copied redaction logic. |
| AWS account bootstrap | `BootstrapConfig`, `administrator_access_policy_document`, `bootstrap_account`, `platform/terraform/global/iam/github-oidc.tf`, `docs/architecture/github-oidc-policy-consolidation-preflight-254.md` | Preserve GitHub OIDC trust, role naming, Terraform-managed production role output, and temporary bootstrap-role cleanup. |
| Instance backend configs | `scripts/bootstrap/terraform_backend.py`, `scripts/terraform/render_aws_backend_configs.py` | Reuse `resolve_instance_backend_dir`, `write_instance_backend_configs`, `backend_config_for_stack`, and `write_portal_remote_state_tfvars`; do not transcribe stack keys. |
| Deploy secrets inventory | `docs/dev/deploy-secrets.md`, `.github/workflows/{deploy.yml,_core.yml,_range.yml,_shifter-platform.yml,_shifter-engine.yml}` | Preserve `AWS_ROLE_ARN*` and `TF_INFRA_STATE_BUCKET*` names and fail-loud missing-secret behavior. |
| AWS Terraform deployment | `_infra_state_bucket`, `_component_stack_dir`, `_deploy_terraform_component`, `terraform_deploy`, `platform/terraform/environments/{dev,proof,prod}` | Keep core/range/portal ordering, per-instance backend path, portal remote-state tfvars, and operator confirmation semantics. |
| GDC cluster bootstrap | `GDCBootstrapConfig`, `GDCHost`, `GDC_API_SERVICES`, `GDC_SERVICE_ACCOUNT_ROLES`, `ensure_gdc_*`, `gdc_bootstrap_cluster` | Keep GDC-on-Compute-Engine topology explicit; do not collapse it into generic Kubernetes or Terraform deploy code. |
| GCP control-plane security | `validate_gcp_control_plane_security_inputs`, `platform/terraform/gcp/**`, `docs/architecture/gke-control-plane-access-preflight.md` | Public hostname, managed TLS, and non-world-open `gke_master_authorized_cidrs` stay fail-closed before Terraform apply. |
| GCP runtime rendering | `scripts/gcp/render_runtime_env.py`, `scripts/gcp/render_private_service_netpol.py`, `platform/charts/shifter/values.yaml` | Reuse the existing runtime-env renderer and Helm value shape; do not create duplicate Terraform-output schemas. |
| GCP/GDC secret handling | `fetch_gcp_secret_payload`, `stage_gcp_control_plane_values`, `runtime_secret_ids`, `docs/architecture/gcp-runtime-secret-env-preflight-1195.md` | Secret values may be read only for deployment-time artifacts; do not log, commit, or promote generated secret-bearing values files. |
| Range egress config | `resolve_shifter_config_path`, `render_range_egress_tfvars`, `shifter/installation` `shifter-config render` | Keep `shifter.yaml` as the source of truth and fail loud when missing; do not parse this config ad hoc in bootstrap. |
| Runner setup | `scripts/bootstrap/runner.py`, `RunnerConfig`, `walkthrough_runner_setup`, `docs/architecture/github-runner-network-isolation-preflight-1222.md` | Preserve manual registration guidance and runner-network guardrails; do not make bootstrap create/register runners implicitly. |
| Test safety | `scripts/bootstrap/tests/conftest.py`, `scripts/bootstrap/tests/test_deploy_helpers.py`, ADR-019 boundary-mock policy | Keep real repo write protection, subprocess mocking, and helper tests; split fixtures into shared test helpers instead of duplicating them. |
| Complexity gate | `scripts/bootstrap/pyproject.toml`, `docs/architecture/python-complexity-gate-preflight.md`, `docs/adr/complexity-backlog.md` | Keep Ruff `C901` active at threshold 15 with no new `# noqa: C901` backlog by default. |
| CI/SAST gates | `.github/workflows/_quality.yml`, `.pre-commit-config.yaml`, `scripts/adr_guard/adr_guard.py` | Bootstrap changes must still pass bootstrap Ruff/format, pytest+coverage, Bandit, and ADR guard. |
| Provisioner patterns for comparison | `shifter/engine/provisioner/terraform_base.py`, `cloud/types.py`, `log_redact.py` | Use as precedent for temp workspace hygiene, provider protocol boundaries, and log redaction, but do not import provisioner internals into bootstrap. |

## Cross-Cutting Layers The Design Must Pass

- Auth surface: AWS auth stays an operator-selected AWS CLI profile locally and
  GitHub OIDC in CI. GCP auth stays `gcloud` plus the temporary Terraform
  bootstrap service account/key flow. Identity Platform first-operator seeding
  must keep `_validate_gcp_bootstrap_operator_email` aligned with the Terraform
  `identity_allowed_email_domain` output.
- Secret-handling surface: GitHub secrets, GCP Secret Manager payloads,
  temporary service-account keys, Guacamole runtime secrets, bootstrap operator
  passwords, and generated Helm values are sensitive. The refactor may move
  code but must not add new secret-bearing CLI flags, logs, committed files, or
  long-lived local artifacts. The current `gh secret set --body ...` exposure
  is legacy behavior behind one helper; do not copy that pattern to new paths.
- Env-binding shape: preserve `AWS_PROFILE`, `TF_INFRA_STATE_BUCKET`,
  `SHIFTER_INSTANCE_DIR`, `SHIFTER_CONFIG`, `SHIFTER_IMAGE_TAG`,
  `GITHUB_SHA`, `GOOGLE_APPLICATION_CREDENTIALS`,
  `GOOGLE_BACKEND_CREDENTIALS`, `GOOGLE_CREDENTIALS`, and the GCP project env
  fallbacks. Temporary env mutation must be restored with `finally`-style
  cleanup as `gcp_terraform_bootstrap_credentials` does today.
- Config validators: keep the Python validators
  (`validate_gcp_control_plane_security_inputs`, `validate_image_tag`,
  `parse_env_contract`, backend env/bucket validation in
  `render_aws_backend_configs.py`) and external validators (Terraform variable
  validation, Helm template/Kubernetes validators, ADR guard, Ruff, Bandit,
  gitleaks, TFLint/actionlint when touched) as the validating layers. Do not
  replace them with string checks scattered through command code.
- OS/process exposure: every local command must be an argv list. Keep
  `_validate_argv` and `_redact_argv_for_log` on every command logged through
  the bootstrap runner. Do not pass secret payload bodies, rendered tfvars,
  service-account JSON, or generated Helm values through argv, shell tracing,
  or diagnostic prints.
- Error-envelope surface: this is a CLI, so `ValueError`, `RuntimeError`, and
  `SystemExit` plus `error()`/`warn()`/`info()` are the current contract. Keep
  failures fail-loud and operator-actionable, but messages should name missing
  fields, paths, commands, secret names, or Terraform output keys, not secret
  values or full generated payloads.
- Observability surface: use the existing terminal UX. Do not introduce a
  second logging framework. Diagnostic output may include environment names,
  stack names, resource names, paths, attempt counts, and sanitized command
  strings; it must not include secret contents or raw service-account JSON.
- Persistence/state surface: Terraform state stays in the existing S3/GCS
  backend layout. Local generated backend configs and portal remote-state
  tfvars stay under the per-instance directory, not the product repo. Temporary
  staging dirs for generated Helm values and service-account keys must remain
  transient.
- Test/enforcement surface: bootstrap tests run from `scripts/bootstrap` with
  `uv run pytest tests/ --cov=.` and are covered by Ruff/format, Bandit, and
  ADR guard. Splitting tests must not reduce coverage of prompts, dry-run
  behavior, command construction, cleanup paths, failure paths, or secret
  redaction.

## Extensibility View

The needed seam is a small dependency boundary around bootstrap execution:
configuration objects, a command runner, prompt/terminal helpers, and explicit
operation functions. The next likely variations are another environment
(`gcp-prod` or a new AWS stack), a new generated Terraform backend stack, or an
additional GDC/GCP deploy prerequisite. Those should be added by extending
environment/stack/config mappings and operation-local constants, not by editing
every command path or introducing a generic workflow engine.

Keep these parameters explicit and close to their owner:

- environment and Terraform stack id;
- AWS profile and region;
- GCP project, region, zone, cluster id, and optional operator email;
- instance directory/backend directory;
- image tag;
- `shifter.yaml` path for range egress rendering;
- retry counts/timeouts for GCP Terraform credential propagation.

## Whole-Repo Surfaces In Scope

Likely implementation surfaces:

- `scripts/bootstrap/deploy.py`
- new or existing modules under `scripts/bootstrap/`
- `scripts/bootstrap/runner.py`
- `scripts/bootstrap/terraform_backend.py`
- `scripts/bootstrap/tests/`
- `scripts/bootstrap/README.md` if module movement changes contributor or
  operator guidance

Comparison and contract surfaces that should usually remain unchanged:

- `scripts/terraform/render_aws_backend_configs.py`
- `scripts/gcp/render_runtime_env.py`
- `scripts/gcp/render_private_service_netpol.py`
- `platform/charts/shifter/**`
- `platform/terraform/environments/**`
- `platform/terraform/global/iam/**`
- `platform/terraform/gcp/**`
- `docs/dev/deploy-secrets.md`
- `.github/workflows/_quality.yml`
- `.pre-commit-config.yaml`
- `docs/adr/**` and `scripts/adr_guard/**` only if enforcement changes

## Gotchas And Anti-Patterns

- Do not create parallel parsers for Terraform outputs, `.env` files, HCL
  tfvars, Helm values, or `shifter.yaml` when an incumbent helper already owns
  the shape.
- Do not conflate GDC cluster bootstrap with GCP control-plane deployment. GDC
  creates the VM Runtime substrate; GCP control-plane Terraform/Helm deploys
  Shifter onto it.
- Do not make `shared`, `shifter_platform`, or the engine provisioner import
  bootstrap modules, and do not import provisioner internals into bootstrap.
  Scripts may use provisioner patterns as precedent, not as runtime coupling.
- Do not weaken Ruff `C901`, Bandit skips, ADR guard, gitleaks, Terraform,
  actionlint, kube-linter, or kubeconform to land the refactor.
- Do not use broad `# noqa`, new `# noqa: C901`, skipped tests, or coverage
  exclusions as substitutes for decomposition.
- Do not preserve one giant test file under a new name. Tests should split by
  behavior and keep common fixtures in `conftest.py` or small helper modules.
- Do not increase first-party internal mock coupling while moving tests. Mock
  process/cloud/network boundaries and assert observable behavior.
- Do not let `os.chdir` or env-var mutation leak across operations. Keep every
  directory/env change scoped and restored in `finally`.
- Do not treat generated Helm values as safe config. `guacamoleRuntimeSecret`
  carries secret values and belongs only in transient deploy artifacts.
- Do not reintroduce DynamoDB Terraform locking in the bootstrap path; the
  current backend contract uses S3 native `use_lockfile = true`.
- Do not hardcode the migrated repository path or use `PaloAltoNetworks/shifter`
  as the active target. The canonical repository is `Brad-Edwards/shifter`.

## Non-Goals

- No cloud-resource redesign, IAM privilege expansion, Terraform state
  migration, Helm chart redesign, workflow gating change, or runner placement
  change.
- No new formal Ground Control requirement, traceability link, database table,
  API, DTO, controller, repository, exception hierarchy, secret-manager
  abstraction, or platform-wide logging layer.
- No behavior change to bootstrap prompts, mandatory/manual step handling,
  `--dry-run`, dependency checks, DNS/ACM/Cognito walkthroughs, or runner
  registration guidance.
- No attempt to solve unrelated deploy reliability, GCP/GDC product posture,
  runtime secret rotation, or production secret incident response.

## Validation Expectations

For the future refactor, run at minimum:

```bash
cd scripts/bootstrap && uv run ruff check . && uv run ruff format --check .
cd scripts/bootstrap && uv run pytest tests/ --cov=.
bandit -r scripts/bootstrap/ --skip B101,B404,B603,B607 --exclude scripts/bootstrap/tests,scripts/bootstrap/.venv
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Add stack-native checks when those surfaces are touched:

- `actionlint` for workflow edits.
- Terraform fmt/validate and `tflint --recursive` for `platform/terraform/**`.
- `cd scripts/gcp && uv run pytest tests/` for GCP script contract changes.
- `cd shifter/shifter_platform && uv run lint-imports --config ../../.importlinter`
  only if the implementation unexpectedly touches platform Python imports.
- Kubernetes `kube-linter` and `kubeconform` only if manifest/chart rendering
  or checked-in Kubernetes manifests change.
