# GKE Control-Plane Access Preflight

Issue: GitHub #957, "[HIGH] GKE control plane publicly accessible with no IP
allowlist" (a duplicate of the implemented #952).

This note records the private control-plane access design and its fail-closed
input boundary.

## Decision

The GCP control plane is private and operators/CI use Connect Gateway.
`gke_master_authorized_cidrs`, wired from the environment root into
`platform-core`, is optional and normally empty. When a connected private
network needs direct API access, both validation layers enforce:

1. The list may be empty.
2. Every entry must carry an explicit `/N` suffix (no bare IPs).
3. Every entry must parse as a CIDR (rejects garbage, bad octets, bad
   prefixes).
4. Every entry must be an IPv4 subnet wholly contained in RFC1918 space.

- **Terraform layer** — `gke_master_authorized_cidrs` in
  `platform/terraform/gcp/modules/platform-core/variables.tf` has no default
  and a `validation` block expressing the contract above. So
  `terraform plan` / `terraform apply` / `terraform test` fail with a clear
  error otherwise — including a direct apply that does not run bootstrap.
- **Bootstrap layer** — `scripts/bootstrap/deploy.py`'s
  `validate_gcp_control_plane_security_inputs` enforces the same four-part
  contract using `ipaddress.ip_network` plus explicit RFC1918 containment
  before it ever reaches `terraform apply`,
  catching the misconfiguration earlier with an operator-facing message.
  Covered by
  `scripts/bootstrap/tests/test_deploy.py::TestGcpControlPlaneSecurityInputs`.

The cluster uses `enable_private_endpoint = true`; bootstrap and CI obtain
credentials through the fleet Connect Gateway rather than public-IP allowlists.

## Canonical Incumbents

- `platform/terraform/gcp/environments/gcp-dev/variables.tf`: environment
  input contract for `gke_master_authorized_cidrs`.
- `platform/terraform/gcp/environments/gcp-dev/main.tf`: passes the
  environment input into `module.platform_core`.
- `platform/terraform/gcp/modules/platform-core/variables.tf`: module input
  contract for optional RFC1918 admin CIDRs, including the `validation` block
  (the Terraform-layer fail-closed gate).
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
- Terraform input validation: the module variable defaults to an empty list;
  any entry must be an RFC1918 IPv4 subnet.
- Terraform resource policy: `google_container_cluster.platform` renders
  `master_authorized_networks_config` whenever the CIDR list is non-empty.
- Bootstrap policy gate: `validate_gcp_control_plane_security_inputs` accepts
  an empty list and rejects malformed, public, IPv6, or world-open entries
  before Terraform apply.
- CI workflow path: `.github/workflows/_gcp-dev.yml` runs Terraform validation
  and deploys from the same environment root consumed by bootstrap. Both its
  initial credential setup and its post-build refresh use
  `gcloud container fleet memberships get-credentials`; direct
  private-endpoint credentials are forbidden because the runner has no route
  to the control-plane RFC1918 address.
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
add parallel variables. Reasonable future sources are connected RFC1918
office/VPN/peered-network CIDRs. Public runner and NAT egress addresses are
not valid for the private endpoint.

## Non-Goals

- Do not restore a public control-plane endpoint for operator convenience.
- Do not add a second GKE module, wrapper schema, validation framework, or
  duplicate Terraform variable for the same allowlist.
- Do not weaken TLS, Cloud Armor, IAP, Workload Identity, Terraform state, or
  Secret Manager controls while changing control-plane access.
- Do not put operator-specific, stale, or overly broad CIDRs into a shared
  module default (the module has no default; CIDRs live in environment
  `terraform.tfvars`).
- Do not use public or world-open networks; leave the list empty for Connect
  Gateway access.

## Validation

Run the repo-required checks for whatever this area's change touches:

- Always (ADR registry / guardrail discipline):

  ```bash
  python3 scripts/adr_guard/adr_guard.py --all --level ci
  ```

- Terraform changes under `platform/terraform/`:

  ```bash
  TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
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
