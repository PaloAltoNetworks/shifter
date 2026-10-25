# GCP range audit telemetry contract

Issue #2535 makes three provider logging controls default-on for GCP ranges:
VPC Flow Logs on range subnets, Cloud NAT logging on range egress, and Vertex AI
Data Access audit logs. For operator settings, log locations, limits, and cost,
see the [operator guide](../../ops/gcp-range-audit-telemetry.md). For the design
guardrails, see the
[architecture preflight](../../architecture/gcp-range-audit-telemetry-preflight-2535.md).

## One policy, two projections

`shared.gcp_range_telemetry.GcpRangeTelemetryPolicy` is the only validator. It is
a closed, frozen Pydantic model with strict booleans, closed enums, and sampling
in `(0, 1]`. The installation package ships it through the
`canonical_gcp_range_telemetry` symlink, like the Mission Control lease policy.

| Step | Owner | Output |
| --- | --- | --- |
| Validate `settings.range_telemetry` | `installation.settings_gcp.GcpBackendSettings` | Normalized policy, or `InstallationConfigError` |
| Terraform projection | `installation.render.render_tfvars` | `range_telemetry = {...}` in the GCP bridge tfvars |
| Runtime projection | `installation.render.render_gcp_range_telemetry_env` (`shifter-config render-gcp-range-telemetry-env`) | `GCP_RANGE_TELEMETRY_POLICY_JSON=...` |
| Runtime env file | `scripts/gcp/render_runtime_env.py` | Canonical JSON in the `platform-runtime` ConfigMap |
| Provisioner Job | `engine.ecs._env`, both provisioner-Job admission policies | Forwarded literal env value |
| Provisioner config | `config._gce.GCERangeCellConfig.range_telemetry` | Parsed policy. Unset means default-on. Blank or invalid fails before any Compute call. |

The bootstrap deploy and `_gcp-dev.yml` run both projections from the same
`shifter.yaml`. Terraform therefore cannot apply one policy while the provisioner
applies another.

## Resource ownership

| Resource | Owner | Logging source |
| --- | --- | --- |
| Range subnets | Provisioner (`gcp_range_cell_resources.subnetwork_resource`) | `plan["telemetry"]["vpc_flow_logs"]` |
| Range-owned Cloud Router and NAT | Provisioner (`router_nat_resource`) | `plan["telemetry"]["nat_logs"]` |
| Shared regional NAT gateways | Provisioner (`gcp_range_cell_shared_nat.allocate_explicit_subnets`) | Same, on every gateway |
| Migration-bridge NATs | Terraform `gcp/modules/range/vpc` | `var.nat_logs` |
| OpenVPN pool subnet and NAT | Terraform `gcp/modules/vpn-pool` | `var.vpc_flow_logs`, `var.nat_logs` |
| Vertex `aiplatform.googleapis.com` audit config | Terraform `gcp/modules/project-audit-config`, called by `platform-core` | `var.range_telemetry.vertex_data_access_logs` |

`google_project_iam_audit_config` is authoritative for its project and service.
`platform-core` is the only owner of the `aiplatform.googleapis.com` entry.

## Convergence

A router patch replaces the whole `nats` list. For this reason, shared NAT
enrollment and removal render `log_config` on every gateway that they write. A
replay is converged only when two conditions are true:

- The requested subnets are enrolled.
- Every owned gateway has the planned `log_config`.

Otherwise the provisioner patches the router under the existing regional
advisory lock.

`_ensure_subnetwork` and `_ensure_router_nat` compare the `log_config` of a
resource that already exists with the plan, using
`gcp_range_cell_resources.log_config_matches`. If they differ, the provisioner
patches the resource. A subnet patch carries the provider `fingerprint`. A
disabled control renders `enable: False`, so replay turns logging off on an
owned resource. The comparison uses `rel_tol=1e-6` for `flow_sampling`, because
the provider stores it as a 32-bit float.

Logging never changes NAT scope. A `none` range still has no `router_nat` and no
`shared_nat`. Every NAT stays `LIST_OF_SUBNETWORKS`.

## Deployment readback

`scripts/gcp/verify_range_audit_telemetry.py` reads three things with fixed-argv
`gcloud` commands that time out after 120 seconds:

- `projects get-iam-policy` for the platform project
- `compute networks subnets list` for the platform project and the range-cell project
- `compute routers list` for the platform project and the range-cell project

The range placement is the Terraform range VPC plus every provisioner per-range
VPC (`shifter-range-<id>`). Ownership decides the result:

- Names in the `range_telemetry_terraform_resources` Terraform output are
  Terraform-owned. Terraform owns the bridge NAT routers and the OpenVPN pool
  subnet and router. A mismatch, or a missing Terraform-owned resource, is
  `FAIL`.
- Every other resource in the placement is provisioner-owned. A mismatch is
  `DRIFT` with a `pending_reprovision` list, because only a later reprovision
  with the deployed runtime policy converges it.

A failed readback in either project is `FAIL`, never an empty deployment. The
script never prints provider payloads, IAM members, or command output.
`gcp_control_plane.verify_gcp_range_audit_telemetry` runs it after
`apply_gcp_control_plane_terraform`, and resolves the range-cell project with
`_range_cell_project_id`. The prepare job in `_gcp-dev.yml` runs it after
`Terraform apply`, with `vars.GCP_RANGE_CELL_PROJECT_ID`. The deploy identity
reads the platform project through `roles/resourcemanager.projectIamAdmin` and
`roles/compute.networkAdmin`. A separate range-cell project must grant the
deploy identity Compute read access; otherwise the readback fails.

## Tests

- Policy: `shifter/shifter_platform/tests/shared/test_gcp_range_telemetry_policy.py`
- Settings and render: `shifter/installation/tests/test_settings_gcp.py`, `test_render.py`
- Runtime env: `scripts/gcp/tests/test_render_runtime_env.py`
- Bootstrap: `scripts/bootstrap/tests/test_gcp_control_plane.py`, `test_gdc_cluster.py`
- Provisioner: `test_config.py`, `test_gcp_range_cell_resources.py`,
  `test_gcp_shared_nat.py`, `test_gcp_range_cells.py`, `test_raes_gcp_plan.py`
- Readback: `scripts/gcp/tests/test_verify_range_audit_telemetry.py`
- Terraform: `range/vpc`, `vpn-pool`, and `project-audit-config` `tests/main.tftest.hcl`
