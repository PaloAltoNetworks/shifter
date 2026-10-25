# GCP range audit telemetry

Part of the Shifter deploy and operations docs; start at the [documentation home](../index.md).

A GCP deployment turns on three provider logging controls for ranges by default.
Each control has a cost, so the operator can change it in `shifter.yaml`. The
deploy validates the result automatically.

| Control | What it records | Default |
| --- | --- | --- |
| VPC Flow Logs | Sampled network flows on every range subnet | On: 5-second aggregation, secondary sampling `0.5`, all metadata |
| Cloud NAT logging | NAT connections and NAT port-exhaustion drops for range egress | On: filter `ALL` (translations and errors) |
| Vertex AI Data Access audit logs | Authenticated Vertex AI calls in the platform project, with caller identity and target resource | On: `DATA_READ` and `DATA_WRITE`, no exempted callers |

## Configure

Add a `range_telemetry` block under `settings` in the GCP `shifter.yaml`. Omit the
block, or any field in it, to keep the default.

```yaml
settings:
  range_telemetry:
    vpc_flow_logs:
      enabled: true
      aggregation_interval: INTERVAL_5_SEC   # INTERVAL_30_SEC, INTERVAL_1_MIN, INTERVAL_5_MIN, INTERVAL_10_MIN, INTERVAL_15_MIN
      flow_sampling: 0.5                     # greater than 0, at most 1
      metadata: INCLUDE_ALL_METADATA         # or EXCLUDE_ALL_METADATA
    nat_logs:
      enabled: true
      filter: ALL                            # or ERRORS_ONLY, TRANSLATIONS_ONLY
    vertex_data_access_logs:
      enabled: true
```

The loader rejects unknown fields, non-boolean `enabled` values, and out-of-range
values before any deploy step runs. To stop a control, set `enabled: false`. A
sampling value of `0` is rejected, because the control would report "on" but
record nothing.

One policy applies to the whole deployment:

- Terraform applies it to the Vertex audit configuration, the Terraform-owned
  migration-bridge NATs, and the participant OpenVPN pool subnet and NAT.
- The provisioner applies it to every range subnet and range NAT gateway that it
  creates. It receives the policy as `GCP_RANGE_TELEMETRY_POLICY_JSON`.
- When a range is provisioned again, the provisioner corrects the logging on the
  subnets and NAT gateways that the range owns. It does not change ranges that
  are not provisioned again.

## Effect of each override on coverage

| Change | Coverage you lose |
| --- | --- |
| `vpc_flow_logs.enabled: false` | No flow records for range subnets. Network forensics for range traffic is not possible. |
| Lower `flow_sampling` | Fewer flow records. Short or low-volume connections are more likely to be absent. |
| Longer `aggregation_interval` | Flows are summarized over longer windows. Timing detail is lost. |
| `EXCLUDE_ALL_METADATA` | Records keep only the 5-tuple and counters. Instance and VPC annotations are removed. |
| `nat_logs.filter: ERRORS_ONLY` | No records of new egress connections. Only port-exhaustion drops are logged. |
| `nat_logs.filter: TRANSLATIONS_ONLY` | No records of dropped packets when NAT ports run out. |
| `nat_logs.enabled: false` | No NAT records for range egress. |
| `vertex_data_access_logs.enabled: false` | Terraform removes the Vertex audit configuration from the platform project. Model calls then follow the project's inherited audit configuration, which is usually off. |

## Validate

The bootstrap deploy (`bootstrap_gcp_control_plane`) and the GCP deploy workflow
run `scripts/gcp/verify_range_audit_telemetry.py` after Terraform apply. It
checks the Terraform range VPC and every per-range VPC (`shifter-range-<id>`) in
the platform project and in the range-cell project (`GCP_RANGE_CELL_PROJECT_ID`).
You can run it yourself with read access to those projects:

```bash
uv run --project scripts/gcp python scripts/gcp/verify_range_audit_telemetry.py \
  --config shifter.yaml --project-id <platform-project> --range-project-id <range-cell-project> \
  --range-network <range-vpc-name> \
  --terraform-subnetwork <name> --terraform-nat-router <name>
```

The `--terraform-*` names come from the `range_telemetry_terraform_resources`
Terraform output. The script prints one line for each control:

```text
vertex_data_access_logs: status=PASS desired=DATA_READ+DATA_WRITE observed=DATA_READ+DATA_WRITE checked=0
vpc_flow_logs: status=DRIFT desired=INTERVAL_5_SEC,0.5,INCLUDE_ALL_METADATA observed=3/4 logging checked=4 pending_reprovision=shifter-r-7-lan
nat_logs: status=PASS desired=ALL observed=2/2 logging checked=2
```

The check treats resources by owner:

- **Terraform-owned resources** are the Vertex audit configuration, the
  migration-bridge NATs, and the OpenVPN pool subnet and NAT. The same deploy
  applies the policy to them, so a mismatch stops the deploy.
- **Provisioner-owned range resources** are range subnets and range NAT
  gateways. They change only when a range is provisioned again with the
  deployed policy. A mismatch is reported as `DRIFT` and lists the resources
  that wait for reprovisioning. It does not stop the deploy, so a policy change
  can deploy.

| Status | Meaning | Deploy result |
| --- | --- | --- |
| `PASS` | Every resource matches the policy. | Continues |
| `FAIL` | A Terraform-owned control is missing or mismatched, or a readback failed. The line lists up to 10 resources. | Stops |
| `DRIFT` | Some provisioner-owned range resources do not match the policy yet. | Continues |
| `DISABLED` | The operator turned the control off. This is a coverage warning. | Continues |
| `NOT_APPLICABLE` | No resources exist in the range placement yet. | Continues |

The Vertex check reads only the project-level audit configuration (the
`aiplatform.googleapis.com` and `allServices` entries). Folder and organization
audit settings are not checked.

To clear `DRIFT`, provision the listed ranges again or recreate them. To
correct a `FAIL`, apply Terraform again. Do not edit Terraform-owned resources
by hand.

## Where the logs go

| Control | Log name | Filter for the Vertex service |
| --- | --- | --- |
| VPC Flow Logs | `projects/<project>/logs/compute.googleapis.com%2Fvpc_flows` | — |
| Cloud NAT | `projects/<project>/logs/compute.googleapis.com%2Fnat_flows` | — |
| Vertex Data Access | `projects/<project>/logs/cloudaudit.googleapis.com%2Fdata_access` | `protoPayload.serviceName="aiplatform.googleapis.com"` |

All three logs go to Cloud Logging in the platform project. Shifter creates no
log sinks or log buckets. In a project with the default routing, the `_Default`
sink writes these logs to the `_Default` log bucket, which keeps them for 30
days. If your project has its own sinks, exclusions, or retention, those apply
instead. Check your project routing before you depend on a retention period.

The `audit_logs` Cloud Storage bucket that the platform creates holds Cloud
Storage usage logs. It does not receive these records.

## Limits of the records

- **Flow logs are sampled.** Google applies a primary sampling rate that you
  cannot change, then the secondary `flow_sampling` rate. Even `1.0` does not
  record every packet. See
  [VPC Flow Logs](https://docs.cloud.google.com/vpc/docs/flow-logs).
- **NAT logs are rate-limited.** Cloud NAT logs only TCP and UDP. It drops entries
  above a per-vCPU rate and can omit some events. If no entry exists, that does
  not prove that no connection occurred. See
  [Cloud NAT logging](https://docs.cloud.google.com/nat/docs/monitoring).
- **Vertex audit coverage depends on the method.** Google lists
  `endpoints.predict` and `endpoints.rawPredict` as `DATA_READ` methods. Before
  you depend on audit records for other methods, check the
  [Vertex AI audit logging](https://docs.cloud.google.com/vertex-ai/docs/general/audit-logging)
  list for the methods your scenarios use.
- **The caller is a shared identity.** Range guests call Vertex AI as the range
  host service account. The audit record identifies that account, not a
  participant or a range.
- **Private Google Access traffic does not use NAT.** Model calls through the
  `private.googleapis.com` VIP do not produce NAT records.
- **Zero-egress ranges have no NAT.** A range with egress mode `none` still gets
  flow logs. Logging never adds a NAT path.

## Cost

These logs are billed. Flow logs and NAT logs are network telemetry logs with
their own price. Data Access audit logs are billed as Cloud Logging ingestion.
Retention longer than the default and routing to other destinations add cost.
See [Google Cloud Observability pricing](https://cloud.google.com/products/observability/pricing).

Cost grows with range traffic, so measure the ingested bytes for your events and
do not use a fixed per-range estimate:

- 5-second aggregation and all metadata give the most detail and the most volume.
- Secondary sampling of `0.5` approximately halves the stored flow records
  compared with `1.0`.
- `ALL` for NAT logs records more than `ERRORS_ONLY`.
- Vertex audit volume grows with the number of model calls.

## Access to the records

Flow metadata, NAT records, and audit caller fields are sensitive operational
data. Data Access audit logs are private logs: a reader needs
`roles/logging.privateLogViewer`. Grant it only to the operators who
investigate incidents. The Vertex audit configuration does not log prompts or
model responses.
