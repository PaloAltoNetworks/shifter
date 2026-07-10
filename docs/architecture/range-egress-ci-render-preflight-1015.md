# Range Egress CI Render Preflight (#1015)

Status: pre-implementation guidance

Date: 2026-06-15

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1015>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #1015 is the shipping
contract: CI deploys must render the range egress Terraform bridge tfvars from
the deployment's `shifter.yaml` instead of carrying a second independently
maintained allowlist in workflow tfvars secrets.

This is deploy plumbing for ADR-017-R4. It must not change firewall enforcement
semantics, Terraform variable names, or the public `settings.range_egress`
contract established by #775 and #958.

## Architecture Decisions

- CI receives the deployment root config as a deployment-scoped GitHub Actions
  secret containing the full `shifter.yaml` for the active backend/environment.
  The implementation should use backend/environment-qualified names, document
  the exact names in `docs/dev/deploy-secrets.md`, and select strictly from the
  active environment. Do not use fallback expressions where an empty active
  secret can fall through to another environment's config.
- The workflow writes that secret to a workspace file and runs
  `shifter-config render` via `uv run --project shifter/installation`, passing
  the config path and `--output <bridge.auto.tfvars>`. The config contents must
  not be passed in argv, echoed, uploaded as an artifact, or committed.
- AWS range keeps `TF_VARS_DEV_RANGE` / `TF_VARS_PROD_RANGE` for non-egress
  deployment overrides such as `agent_s3_bucket` and `vm_series_ami_id`.
  `victim_allowed_cidrs` moves out of that whole-file secret and into the
  generated `victim_allowed_cidrs.auto.tfvars`.
- GCP keeps `_gcp-dev.yml`'s generated `local.auto.tfvars` for project,
  hostname, identity, region, and GKE control-plane inputs. Range egress moves
  into a separate generated `range_egress.auto.tfvars` rendered by
  `shifter-config render`.
- `scripts/bootstrap/deploy.py` should follow the same GCP bridge contract when
  it applies `platform/terraform/gcp/environments/<env>`: render
  `range_egress.auto.tfvars` from a provided root config before Terraform
  consumes variables, and fail loud if the root config input is missing.
- Missing root config input is a hard deploy preflight failure. The error may
  name the missing secret/input and point at `docs/dev/deploy-secrets.md`; it
  must not print the secret payload or rendered HCL body.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #1015 |
| --- | --- | --- |
| Root config parsing | `shifter/installation/loader.py`, `schema.py`, `errors.py` | Execute `shifter-config render`; do not parse YAML or validate CIDRs in workflow shell. |
| Range egress policy | `shifter/installation/range_egress.py`, `render.py`, `tests/test_render.py` | Reuse `RangeEgressPolicy` and `render_tfvars`; do not duplicate mode/CIDR rules. |
| AWS range tfvars overlay | `.github/workflows/_range.yml`, `platform/terraform/environments/{dev,prod}/range/local.auto.tfvars.example` | Keep the non-egress whole-file secret; render egress into its dedicated auto tfvars file before `terraform validate/plan/apply`. |
| GCP deploy overlay | `.github/workflows/_gcp-dev.yml`, `scripts/bootstrap/deploy.py`, `platform/terraform/gcp/environments/gcp-dev` | Keep existing project/hostname/control-plane rendering; add the egress bridge file as a separate generated Terraform input. |
| Terraform validation | AWS range env/module `variables.tf`, GCP env/module `variables.tf`, `terraform_data.range_egress_invariant` | Root validation and Terraform validation are complementary; do not remove the direct-Terraform backstops. |
| Generated-file hygiene | `.gitignore`, ADR-004-R8, ADR-017-R2 | Generated bridge tfvars stay gitignored and ephemeral. Do not upload them as durable artifacts. |
| Workflow guardrails | ADR-003, ADR-004-R1, ADR-011-R7, `.gc/plan-rules.md` | Workflow edits must preserve self-hosted runner gating, saved-plan apply rules where they apply, fail-loud checks, and `actionlint`. |

## Cross-Cutting Layers

- Auth surface: AWS OIDC role assumption and GCP Workload Identity stay
  unchanged. Rendering the tfvars needs repository contents plus Actions
  secret injection only; it must not require new cloud IAM privileges.
- Secret-handling surface: `shifter.yaml` stores secret references, not secret
  values, but CI should still treat the deployment-specific file as sensitive
  operational input. Write it with shell redirection to a file; never echo it,
  pass it as command-line text, or include it in summaries/artifacts.
- Environment binding: select the active deployment config using explicit
  environment/backend branches, matching `_range.yml`'s existing strict
  `inputs.is_dev` pattern. Empty active input fails; it never reuses another
  environment's secret.
- Config shape: `load_root_config` must run before any Terraform step consumes
  bridge variables, preserving duplicate-key rejection, merge-key rejection,
  backend/profile validation, secret-reference grammar, and
  `settings.range_egress` normalization.
- Terraform shape: AWS consumes only `victim_allowed_cidrs`; GCP consumes
  `range_egress_mode` and `range_egress_allowed_cidrs`. Provider variables
  remain internal bridges and keep their existing validation/precondition
  semantics.
- OS/process exposure: command invocations should pass file paths and argv
  arrays, not YAML or HCL contents. Avoid `terraform -var` for the rendered
  CIDRs and avoid shell string manipulation of CIDR lists.
- Error envelopes: renderer failures use `InstallationConfigError` through the
  CLI. Workflow-local missing-input checks use `::error::` messages that name
  only the missing input and docs path.
- Persistence and observability: generated tfvars are workspace-local inputs to
  Terraform. The evidence surface remains Terraform plan/apply output and cloud
  firewall resources/logs, not application logs or runtime settings.

## Extensibility Seam

The seam is provider-neutral policy rendering parameterized by config path,
backend selected in `shifter.yaml`, active deployment environment, and output
path. Future scenario overrides, composable allowlist sets, or an explicit
`allow-all` mode should extend `RangeEgressPolicy` and `render_tfvars`; they
must not add provider-local CIDR secrets, workflow variables, or parallel HCL
schemas.

If the workflow duplication becomes material, extract only a small renderer
wrapper that accepts `(config path, output path)` and delegates to
`shifter-config render`. Do not introduce a second YAML parser or provider
switch outside the installation package.

## Gotchas And Anti-Patterns

- Do not leave `victim_allowed_cidrs`, `range_egress_mode`, or
  `range_egress_allowed_cidrs` in `TF_VARS_*_RANGE`, GCP deploy secrets, or
  operator-authored `local.auto.tfvars`.
- Do not render egress into `local.auto.tfvars`; that risks clobbering
  unrelated deployment overrides and recreates the drift-prone mixed file.
- Do not use checked-in `.shifter.yaml`; it is the MCP ops policy namespace, not
  the root installation config.
- Do not conflate range egress with `GCP_MASTER_AUTHORIZED_CIDRS`,
  `operator_admin_cidrs`, AWS `victim_allowed_domains`, NGFW bypasses,
  Kubernetes NetworkPolicy egress, portal inspection, or operator SSH/RDP
  source allowlists.
- Do not weaken the default-deny/firewall rule ordering, AWS rule chunking, GCP
  firewall priorities, or direct Terraform validation while changing the CI
  input source.
- Do not make a missing root config silently mean `status-quo`; missing input is
  an operator/deploy configuration error.

## Non-Goals

- No firewall semantics, NAT, route table, security group, NetworkPolicy, or
  cloud IAM behavior change.
- No root schema redesign, new DTO/controller/service/repository, runtime
  setting, Django setting, or exception hierarchy.
- No new provider-specific egress schema, no committed allowlist, and no
  per-workflow CIDR variables.
- No scenario-level overrides, composable allowlist sets, admin UI, RBAC, or
  explicit `allow-all` mode.

## Validation Expectations

The implementation that touches workflows, Terraform deploy scripts, and docs
should run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
actionlint
cd shifter/installation && uv run pytest tests/test_render.py tests/test_range_egress.py
```

Also run Terraform formatting/validation or TFLint for any changed Terraform
roots/modules, and update `docs/dev/deploy-secrets.md` plus
`docs/architecture/range-egress-ip-allowlist.md` to reflect the final secret
names and generated-file flow.
