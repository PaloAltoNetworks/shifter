# GKE Control-Plane Access Preflight

Issue: GitHub #957, "[HIGH] GKE control plane publicly accessible with no IP
allowlist" (a duplicate of the implemented #952).

This note records the control-plane-access design and the boundary for the
future private-endpoint change. It does not introduce a new platform
abstraction; it documents the existing one so a later change in this area
stays inside it.

## Decision

The GCP control plane keeps the public GKE API endpoint only while it is
constrained by `master_authorized_networks_config`. The canonical input is
`gke_master_authorized_cidrs`, wired from the environment root into
`platform-core`. The insecure-allowlist footgun is closed at two layers,
both fail-closed and enforcing the same contract from the **parsed** prefix —
not from string-suffix matching that could miss alternate spellings:

1. The list must be non-empty.
2. Every entry must carry an explicit `/N` suffix (no bare IPs).
3. Every entry must parse as a CIDR (rejects garbage, bad octets, bad
   prefixes).
4. The parsed prefix length must be `> 0` (rejects every spelling of `/0`,
   IPv4 or IPv6, from the parsed prefix number).

- **Terraform layer** — `gke_master_authorized_cidrs` in
  `platform/terraform/gcp/modules/platform-core/variables.tf` has no default
  and a `validation` block expressing the four-part contract above
  (`length(...) > 0` + per-entry `cidrhost(cidr, 0)` for parse-validity,
  `regex("/[0-9]+$", cidr)` for explicit suffix, and
  `tonumber(regex("/([0-9]+)$", cidr)[0]) > 0` for the parsed prefix). So
  `terraform plan` / `terraform apply` / `terraform test` fail with a clear
  error otherwise — including a direct apply that does not run bootstrap. The
  cluster runs with `enable_private_endpoint = false`, so this allowlist is
  the only network-level restriction on the public API server, hence it is
  mandatory.
- **Bootstrap layer** — `scripts/bootstrap/deploy.py`'s
  `validate_gcp_control_plane_security_inputs` enforces the same four-part
  contract (`"/" in cidr`, then `ipaddress.ip_network(cidr, strict=False)`,
  then `network.prefixlen > 0`) before it ever reaches `terraform apply`,
  catching the misconfiguration earlier with an operator-facing message.
  Covered by
  `scripts/bootstrap/tests/test_deploy.py::TestGcpControlPlaneSecurityInputs`.

The long-term private-endpoint option remains valid, but it is a separate
design change because bootstrap, CI deploys, `get-gke-credentials`, Helm,
kubectl, and operator access would all need a private network path such as
VPN, bastion, IAP-accessible runner placement, or equivalent. Such a change
must flip `enable_private_endpoint` and relax the `gke_master_authorized_cidrs`
validation together.

## Canonical Incumbents

- `platform/terraform/gcp/environments/gcp-dev/variables.tf`: environment
  input contract for `gke_master_authorized_cidrs`.
- `platform/terraform/gcp/environments/gcp-dev/main.tf`: passes the
  environment input into `module.platform_core`.
- `platform/terraform/gcp/modules/platform-core/variables.tf`: module input
  contract for authorized admin CIDRs, including the non-empty `validation`
  block (the Terraform-layer fail-closed gate).
- `platform/terraform/gcp/modules/platform-core/main.tf`: owns the
  `google_container_cluster.platform` resource and the
  `master_authorized_networks_config` rendering.
- `scripts/bootstrap/deploy.py`: bootstrap preflight gate via
  `validate_gcp_control_plane_security_inputs`.
- `scripts/bootstrap/tests/test_deploy.py`: regression tests for security
  input parsing and fail-closed behavior
  (`TestGcpControlPlaneSecurityInputs`).
- `docs/adr/index.yaml` `ADR-008`: accepted repo policy for GCP bootstrap
  fail-closed behavior and authorized admin CIDRs (this note is listed as
  ADR-008 evidence).
- `platform/terraform/gcp/README.md`: operator-facing GCP Terraform contract.

## Cross-Cutting Layers

Security layers any change in this area must satisfy:

- Terraform input shape: `gke_master_authorized_cidrs` stays a `list(string)`
  and is passed through the environment root instead of hardcoded in the
  module.
- Terraform input validation: the module variable has no default and a
  `validation` block requiring a non-empty list of valid CIDRs with no `/0`
  global range; do not reintroduce a default or weaken the validation while
  the endpoint is public.
- Terraform resource policy: `google_container_cluster.platform` renders
  `master_authorized_networks_config` whenever the CIDR list is non-empty.
- Bootstrap policy gate: `validate_gcp_control_plane_security_inputs` rejects
  an empty list, malformed CIDR entries, and `/0` ranges before Terraform
  apply — the same contract the Terraform `validation` block enforces.
- CI workflow path: `.github/workflows/_gcp-dev.yml` continues to run
  Terraform validation and deploys from the same environment root consumed by
  bootstrap.
- Secret handling: CIDR allowlists are not secrets and must not be routed
  through Secret Manager, GitHub secrets, kube manifests, or runtime env
  files.
- OS/process exposure: if a future workflow supplies CIDRs dynamically, avoid
  embedding credentials or tokens in process argv; CIDRs themselves may be
  Terraform variables, but authentication remains in the existing GCP auth
  path.
- Error handling: fail through the existing bootstrap `error(...)` plus
  `sys.exit(1)` path and Terraform variable-validation errors, without
  creating a new exception hierarchy.
- Observability: rely on Terraform plan/apply diffs and bootstrap error text;
  do not add runtime application logging for control-plane network policy.

## Extensibility Seam

The seam is the environment-level `gke_master_authorized_cidrs` value. Future
changes should extend that parameter, not duplicate the cluster resource or
add parallel variables. Reasonable future sources include CI runner egress
CIDRs, office/VPN CIDRs, NAT gateway public IPs, or a switch to a private
endpoint with corresponding private runner/operator reachability.

## Non-Goals

- Do not convert the cluster to `enable_private_endpoint = true` unless the
  change also designs and validates the private access path for bootstrap,
  CI, Helm, and kubectl, and relaxes the `gke_master_authorized_cidrs`
  validation in the same change.
- Do not add a second GKE module, wrapper schema, validation framework, or
  duplicate Terraform variable for the same allowlist.
- Do not weaken TLS, Cloud Armor, IAP, Workload Identity, Terraform state, or
  Secret Manager controls while changing control-plane access.
- Do not put operator-specific, stale, or overly broad CIDRs into a shared
  module default (the module has no default; CIDRs live in environment
  `terraform.tfvars`).
- Do not use `0.0.0.0/0` / `::/0` as a convenience allowlist — both the
  Terraform `validation` block and the bootstrap preflight reject `/0` ranges;
  keep entries scoped to specific admin networks (and avoid broad
  cloud-provider ranges even though they are not literally `/0`).

## Validation

Run the repo-required checks for whatever this area's change touches:

- Always (ADR registry / guardrail discipline):

  ```bash
  python3 scripts/adr_guard/adr_guard.py --all --level ci
  ```

- Terraform changes under `platform/terraform/`:

  ```bash
  cd platform/terraform && tflint --recursive --config ../../.tflint.hcl
  # plus the native validation CI runs from the environment root, e.g.:
  cd platform/terraform/gcp/environments/gcp-dev && terraform init -backend=false && terraform validate
  ```

- GitHub Actions workflow changes under `.github/workflows/`:

  ```bash
  actionlint
  ```

- Bootstrap changes (`scripts/bootstrap/deploy.py` or its tests):

  ```bash
  python3 -m pytest scripts/bootstrap/tests/test_deploy.py -k GcpControlPlaneSecurityInputs
  ```

- Any other touched subsystem also runs its stack-native checks (e.g.
  `ruff` / `mypy` for `shifter_platform` Python, `kube-linter` / `kubeconform`
  for `platform/k8s/`, `pre-commit run --all-files` for the full set).
