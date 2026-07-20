# Range Egress Allowlist Render Preflight (#958)

Status: pre-implementation guidance

Date: 2026-06-15

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/958>

## Scope Boundary

This is a requirement-free preflight. GitHub issue #958 is the shipping
contract: the range egress allowlist must have one authoritative rendered
source, so the configured policy and deployed firewall rules cannot drift.

This is plumbing for the existing ADR-017 range-egress policy. It must not
change the policy semantics established by PLAT-220 / #775.

## Architecture Decisions

- The canonical operator intent remains
  `shifter.yaml.settings.range_egress`, validated and normalized by
  `shifter/installation/range_egress.py` through `load_root_config`.
- Provider-specific Terraform variables are bridge outputs, not public
  configuration. AWS still receives `victim_allowed_cidrs`; GCP still receives
  `range_egress_mode` and `range_egress_allowed_cidrs`.
- The renderer must consume the normalized `RangeEgressPolicy` shape. Do not
  parse raw YAML, split CIDR strings in shell, or maintain a second schema.
- The rendered Terraform input may be written into the existing gitignored
  deployment override path, but the allowlist values must be generated from the
  canonical root config rather than hand-copied into a second gitignored file.
- CIDRs are operator configuration, not secrets. They may appear in Terraform
  plans and provider rule definitions, but they should not be routed through
  secret stores, Kubernetes Secrets, or runtime secret env vars.
- Direct Terraform validation remains a backstop for operators who bypass the
  root renderer. It must mirror the public `RangeEgressPolicy` contract.

## Canonical Incumbents

| Concern | Canonical incumbent | Guardrail for #958 |
| --- | --- | --- |
| Root config parsing and error aggregation | `shifter/installation/loader.py`, `schema.py`, `errors.py` | Use `load_root_config`; keep duplicate-key rejection, merge-key rejection, backend dispatch, and `InstallationConfigError` aggregation centralized. |
| Range egress schema | `shifter/installation/range_egress.py`, `shifter/installation/tests/test_range_egress.py` | Reuse `RangeEgressPolicy`; do not duplicate CIDR validation or mode invariants. |
| Backend bundle contract | `shifter/installation/contract.py`, `registry.py` | Renderer metadata should fit the existing `CommandSpec` / generated-output model when backend migrations wire it in; commands stay argv arrays. |
| AWS bridge | `platform/terraform/modules/range/vpc/{variables,firewall}.tf`, `platform/terraform/environments/{dev,prod}/range/{variables,main,terraform.tfvars}` | Keep `victim_allowed_cidrs` internal and preserve existing Network Firewall rule ordering and chunking behavior. |
| GCP bridge | `platform/terraform/gcp/modules/platform-core/{variables,main}.tf`, `platform/terraform/gcp/environments/gcp-dev/{variables,main,terraform.tfvars}` | Keep `range_egress_mode` / `range_egress_allowed_cidrs` as internal bridge variables and preserve deny-all plus TCP/443 allowlist semantics. |
| Deploy rendering conventions | `.github/workflows/_range.yml`, `.github/workflows/_gcp-dev.yml`, `scripts/gcp/render_runtime_env.py`, `scripts/gcp/render_private_service_netpol.py` | Render before Terraform consumes variables; fail loud on missing inputs; keep generated files in ignored workspace paths where appropriate. |
| Enforcement and docs | ADR-017 in `docs/adr/index.yaml`, `.gitignore`, `docs/dev/deploy-secrets.md`, `scripts/adr_guard/adr_guard.py` | Update docs/guardrails with any new renderer contract; do not weaken ignored-file or plaintext-secret checks. |

## Cross-Cutting Layers

- Auth surface: no Cognito, Identity Platform, Django auth, GitHub OIDC, AWS
  role-assumption, or GCP Workload Identity behavior should change. The
  renderer only prepares Terraform input.
- Secret-handling surface: allowlist CIDRs remain non-secret configuration. If
  the renderer shares a file with deployment-secret-derived Terraform HCL, do
  not print the file body, upload it as an artifact, or pass it through argv.
- Env-binding and config shape: `shifter.yaml` is validated by the
  installation loader; Terraform roots validate provider bridge variables;
  workflows pass only explicit environment inputs and must fail loud when
  required source config is absent.
- OS/process exposure: use file input/output and structured argv-style command
  specs. Avoid `terraform -var`, shell string CIDR parsing, and diagnostics
  that echo rendered HCL.
- Error envelopes: root-config failures surface through
  `InstallationConfigError`; workflow failures should name the missing input and
  docs path without printing values; Terraform failures remain Terraform
  validate/plan/apply errors.
- Runtime/API surface: no DTO, controller, service, repository, Django setting,
  or application exception hierarchy is needed for this issue.
- Kubernetes policy surface: do not change Helm NetworkPolicy, GCP static base
  manifests, or generated private-service NetworkPolicy while wiring range VPC
  egress Terraform inputs.
- Observability: Terraform plans, AWS Network Firewall rule groups, and GCP VPC
  firewall rules are the evidence surface. Application logs should not become
  the source of truth for network reachability.

## Extensibility Seam

The seam is a provider-neutral policy-to-bridge renderer parameterized by
backend, environment/Terraform root, and output path. Future changes such as
scenario-level overrides, named allowlist sets, or a deliberate `allow-all`
mode should extend `RangeEgressPolicy` and the renderer mapping rather than
adding provider-local allowlist files or parallel workflow variables.

## Gotchas And Anti-Patterns

- Do not require operators to maintain the same CIDRs in both `shifter.yaml`
  and `local.auto.tfvars` / `range_egress*.auto.tfvars`.
- Do not expose the AWS `victim_allowed_cidrs` name as the public platform
  contract.
- Do not conflate CIDR egress allowlists with AWS domain SNI allowlists, NGFW
  licensing bypasses, GKE master authorized networks, Kubernetes NetworkPolicy
  egress, or operator SSH/RDP source CIDRs.
- Do not use `0.0.0.0/0` or `::/0` as an allowlist sentinel. A future
  allow-all posture must be an explicit mode with a documented rationale.
- Do not let `enable_network_firewall = false` silently coexist with an AWS
  allowlist that operators expect to be enforced.
- Do not overwrite unrelated deployment-owned Terraform overrides when adding
  rendered range-egress bridge values.
- Be careful reducing AWS Network Firewall CIDR chunks; existing comments in
  `firewall.tf` describe provider ordering and manual cleanup risks.

## Non-Goals

- No firewall rule semantic change, route change, NAT change, or NetworkPolicy
  change.
- No scenario-level overrides, composable allowlist sets, admin UI, RBAC, or
  new `allow-all` mode.
- No new secret abstraction, runtime settings path, API, DTO, service,
  repository, exception hierarchy, or logging framework.
- No replacement of Terraform validation; root validation and Terraform
  validation are complementary layers.
- No implementation in this preflight note.

## Validation Expectations

For the implementation change, run the repo-required architecture and platform
checks for the touched surfaces. At minimum for architecture/workflow/Terraform
edits:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run the relevant renderer/unit tests, Terraform formatting/validation for
edited roots, and `actionlint` for workflow changes.
