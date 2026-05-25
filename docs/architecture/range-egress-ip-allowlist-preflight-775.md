# Range Egress IP Allowlist Preflight

Scope: GitHub #775 / PLAT-220. This note records repository-wide architecture
guardrails for the upcoming implementation. It is not an implementation plan.

## Architecture Decisions

- The public configuration surface for range egress IP allowlists must live under
  the root installation configuration (`shifter.yaml`) as provider-neutral
  operator intent. Do not add a separate root parser, scenario template field,
  Django setting, or ad hoc Terraform-only contract for PLAT-220.
- The installation package remains the validation boundary. Backend-specific
  settings models should validate and normalize any `range_egress` settings, and
  shared CIDR validation logic should be reused across AWS and GCP instead of
  duplicating provider-local validators.
- The user-facing shape must express platform concepts, not cloud firewall
  syntax. A suitable seam is a provider-neutral range egress policy object with
  parameters such as allowed CIDR blocks and an explicit default policy/mode.
- Omitted allowlist configuration must be documented separately from an explicit
  empty allowlist. For backward compatibility, omission should preserve the
  current backend status quo unless the implementation deliberately changes the
  documented platform default.
- Domain allowlists, NGFW licensing/provisioning bypasses, control-plane
  authorized networks, Kubernetes NetworkPolicy egress, and range egress CIDR
  allowlists are separate concepts. Do not collapse them into one schema or one
  policy name.
- CIDR blocks are operator configuration, not secrets. They must not be routed
  through secret references, Kubernetes Secrets, or runtime secret env vars.

## Canonical Incumbents

- Root installation config: `shifter/installation/schema.py`,
  `shifter/installation/loader.py`, `shifter/installation/contract.py`,
  `shifter/installation/registry.py`, `shifter/installation/examples/*.yaml`,
  and `docs/architecture/root-configured-backend-bundles.md`.
- Existing CIDR/security validation precedent:
  `scripts/bootstrap/deploy.py` for parsed CIDR checks and
  `platform/terraform/gcp/modules/platform-core/variables.tf` for Terraform
  validation of operator CIDR input.
- AWS range egress incumbent:
  `platform/terraform/modules/range/vpc/firewall.tf`,
  `platform/terraform/modules/range/vpc/variables.tf`,
  `platform/terraform/environments/*/range/main.tf`, and the existing
  `victim_allowed_cidrs` input. This is an implementation detail to bridge from,
  not a public platform name to expose.
- GCP network incumbent:
  `platform/terraform/gcp/modules/platform-core/{main,variables,outputs}.tf`,
  `platform/terraform/gcp/environments/*`, `scripts/bootstrap/deploy.py`, and
  `scripts/gcp/render_runtime_env.py`.
- Kubernetes and ADR guardrails:
  `platform/charts/shifter/templates/networkpolicies.yaml`,
  `platform/k8s/gcp/base/networkpolicies.yaml`, `.importlinter`,
  `.tflint.hcl`, `.kube-linter.yaml`, and `scripts/adr_guard/adr_guard.py`.
- Runtime shared contracts:
  `shifter/cyberscript/schemas/*`,
  `shifter/shifter_platform/shared/schemas/*`,
  `shifter/shifter_platform/shared/errors.py`,
  `shifter/shifter_platform/shared/exceptions.py`, and
  `shifter/shifter_platform/shared/log_sanitize.py`. These are relevant only if
  the implementation crosses into runtime/API surfaces.

## Cross-Cutting Layers The Design Must Pass

- Root YAML parser: reuse `InstallationConfig.load_path` / the installation
  loader so duplicate-key rejection, merge-key rejection, path-based error
  reporting, and backend dispatch remain centralized.
- Backend settings shape: use backend bundle settings models with
  `extra="forbid"` semantics. Reject malformed CIDRs, missing prefix lengths,
  duplicate entries after normalization, and ambiguous `/0` allowlist entries
  unless an explicit allow-all mode is part of the documented platform contract.
- Error handling: raise sanitized `InstallationConfigError` instances from
  installation validation. If a runtime API path is added later, surface errors
  through the shared error envelope instead of leaking provider exceptions.
- Secret handling: keep CIDRs out of secret references and generated secret
  destinations. Generated outputs should preserve the existing sensitivity
  classifications in the installation contract.
- OS/process exposure: pass generated Terraform or backend commands as argv
  arrays, following existing command-spec and bootstrap patterns. CIDRs may
  appear in plan files or command logs, but credentials must not be introduced
  beside them.
- Terraform validation: mirror root-config validation in AWS and GCP Terraform
  variables so direct Terraform use fails consistently. Do not rely on only one
  layer for invalid CIDR rejection.
- Kubernetes policy guardrails: do not broaden platform pod egress while adding
  range network egress policy. Any NetworkPolicy changes must still satisfy
  ADR-006 and the guard that rejects broad egress CIDR blocks.
- Import boundaries: keep reusable config validation in installation/shared
  code. Do not make platform, CMS, or engine internals import each other to
  obtain allowlist parsing.
- Observability/logging: prefer Terraform plan/apply output and cloud-native
  firewall/NAT logs for policy evidence. If application logs include allowlist
  values, sanitize user-controlled text and avoid logging noisy full lists where
  counts or normalized hashes are enough.

## Extensibility Boundary

The required seam is a provider-neutral range egress policy object in root
settings that can later be refined by PLAT-221, PLAT-222, and PLAT-223 without
rewriting the provider contract. The platform-level schema should leave room for
scenario overrides and named/composable sets, but PLAT-220 should only establish
the platform default policy and allowed CIDR blocks.

## Gotchas And Anti-Patterns

- Do not expose the legacy AWS `victim_allowed_cidrs` name as the platform
  contract. Bridge to it internally until the Terraform module can be renamed.
- Do not treat GCP ingress firewall rules or Kubernetes NetworkPolicies as range
  egress enforcement. GCP currently has range Cloud NAT behavior that must be
  addressed separately from ingress controls.
- Do not silently allow `enable_network_firewall = false` on AWS together with
  an explicit egress allowlist if that bypasses enforcement.
- Be careful reducing AWS Network Firewall rule-group chunks. Existing comments
  warn that AWS policy update ordering can leave unused stateful rule groups
  requiring manual cleanup.
- Do not use `0.0.0.0/0` or `::/0` as a casual allowlist value. If allow-all is
  a supported mode, make it an explicit mode with clear documentation.
- Do not couple the root config to AWS Suricata rule strings, GCP firewall
  priority/direction syntax, or any provider-native resource naming.
- Do not add scenario-level allowlist overrides, composable allowlist sets, admin
  UI, or RBAC in PLAT-220; those belong to PLAT-221, PLAT-222, and PLAT-223.

## Validation Expectations

For the implementation change, run the repository-required architecture checks
for touched areas. At minimum, architecture/platform changes should pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

Also run the stack-native checks for any touched subsystem, including
import-linter for `shifter/shifter_platform`, Terraform validation/tflint for
platform Terraform, actionlint for workflow changes, and the Kubernetes linters
for Kubernetes policy changes.
