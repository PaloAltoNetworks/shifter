# GCP range audit telemetry preflight (#2535)

Architecture guidance for [#2535](https://github.com/Brad-Edwards/shifter/issues/2535).
The supplied issue is the delivery contract; no Ground Control requirement is
attached. This note records intended behavior, not implemented defaults or an
implementation plan. It applies ADR-008/011 config and identity boundaries,
ADR-026-R6 NAT ownership, ADR-039 lifecycle/error contracts, and ADR-064 as
qualified by ADR-068: keyless direct access is the only supported model path;
the broker remains parked.

## Ownership and selected defaults

| Control | Intended default | Canonical owner and consumers |
| --- | --- | --- |
| Range subnet flow records | Enabled; `INTERVAL_5_SEC`, secondary sampling `0.5`, `INCLUDE_ALL_METADATA`; no restrictive flow filter | `engine/provisioner/gcp_range_cell_resources.py:subnetwork_resource`, consumed by `gcp_range_cells.py` and `raes_gcp_apply.py`; keep policy in the existing `GCERangeCellConfig`/typed plan path. |
| Range egress NAT records | Enabled with filter `ALL` (translations and errors) on every applicable gateway | `gcp_range_cell_resources.py:router_nat_resource` for range-owned routers; `gcp_range_cell_shared_nat.py:allocate_explicit_subnets` and its serialized enrollment/removal path for shared routers; Terraform `gcp/modules/range/vpc/main.tf` for migration bridges in primary and pooled regions. |
| Vertex Data Access | `DATA_READ` and `DATA_WRITE` for `aiplatform.googleapis.com`, without exempted callers | Project-level Terraform `gcp/modules/platform-core/main.tf`, following the existing `dynamic_secret_data_read` resource pattern. Own each project/service pair once. |
| Destination and retention | Cloud Logging's existing routing; fresh unmodified projects use `_Default` with 30-day retention | Deployment/project operator owns sinks, exclusions, bucket location, access and retention. This issue does not take over existing bucket policy or create per-range sinks/buckets. Effective routing/retention must be reported. |

Paths above are relative to `shifter/` or `platform/terraform/` as indicated.
The flow defaults match Terraform's existing subnet `log_config` in
`portal/vpc`, `vpn-pool`, `github-runner-network`, and image-build modules.
Those subnet blocks are useful incumbents, not proof of participant-subnet
coverage: Terraform's range VPC module does not create the dynamic guest subnets.
Include all subnets realized by the supported GCE paths, including generated
backend/host networks; do not key coverage on scenario identities.

The `vpn-pool` subnet/NAT is a separate Terraform owner inside the range VPC;
state its coverage explicitly when installed. Platform GKE, runner, and image
builder networks are separate scopes; do not turn this issue into a blanket
rewrite of their telemetry policies.

Apply audit configuration where Vertex calls consume the target project, not
blindly where the calling VM lives or in `dynamic_secret_project_id`.
The supported direct identity's predict grant is in the platform project
(`portal/iam/main.tf`); range placement resolves its own project through
`config/_gce_required.py`. Inventory network and model target projects separately.
For an operator-managed external target, report missing management authority or
coverage rather than fabricating success or expanding provisioner IAM.
Enabling the API, attaching an identity and enabling audit logging are separate
controls. `platform-core` / `project-services` remains the API-enablement owner;
verify Logging API readiness for readback in each observed project rather than
depending on a bootstrap-only API list. `DATA_WRITE` configuration grants no
write permission to the guest.

## Reconciliation and extensibility

Shared NAT allocators reconstruct the entire `nats` list on enrollment **and
removal**. Logging must survive both operations, multiple gateways, regional
placement and no-op replays. Existing membership does not prove logging is
correct: the shared path returns early on membership, and `_ensure_subnetwork`
and `_ensure_router_nat` currently skip existing resources. A retry that observes
a partially created resource must converge or report the telemetry mismatch;
do not mark existence as compliant. Limit patches to owned controls, preserve
unrelated gateway settings, and keep the existing regional PostgreSQL advisory
lock, capacity checks, provider-operation waits and ownership checks. Never
patch a Terraform-owned bridge from a range job.

Logging does not authorize a NAT path. Preserve `LIST_OF_SUBNETWORKS`, existing
egress policy and the absence of NAT for `none` ranges. NAT validation there is
explicitly not applicable with a reason, not a failure or an enabled control.
Private Google Access model traffic need not traverse NAT; do not expect every
Vertex request to produce a NAT record. GDC VM Runtime is not a GCE subnetwork:
report backend-specific applicability without claiming equivalent guest flow
coverage or adding another backend implementation.

The extension seam is the existing closed `installation.settings_gcp` operator
settings and `GCERangeCellConfig`, projected through typed plans into provider
bodies. Provide explicit enable overrides and bounded flow cost tuning without
a new generic telemetry framework or copied provider schema. Missing settings
select the documented defaults; explicit disabling, zero sampling, restrictive
filters or reduced metadata must describe lost coverage. One deployment policy
owns shared NAT logging: conflicting per-range preferences cannot configure the
same gateway. Terraform variables and runtime environment values are generated
bridges from the same operator intent, not independently maintained overrides.
Keep provider-specific configuration out of scenario artifacts and closed
`shared.range_cells` / `shared.operation_envelope` wire payloads. Bucket-retention
variation belongs at the project operator seam, not in guest/range state.

## Cross-cutting gates the design must pass

| Layer / incumbent | Required fit |
| --- | --- |
| Config ingestion: `installation.loader`, `schema`, `settings_gcp`, `errors` | Preserve safe YAML loading, duplicate-key rejection and `extra='forbid'`. Use Pydantic strict booleans, bounded numeric fields and closed enums; errors use `ConfigIssue`/`InstallationConfigError` without rejected values. Publish generated settings schema through `installation.publication`, never hand-edit it. |
| Config projection: `installation.render`, `scripts/gcp/render_runtime_env.py`, `scripts/bootstrap/gcp_control_plane.py` | Reuse root-config-to-Terraform and runtime projections in both bootstrap/Helm and reusable deploy paths. Validate direct Terraform bridge inputs too. Do not read raw YAML or invent a second semantic validator in the renderer. |
| Runtime config: `provisioner/config/_gce.py`, `_env.py`, typed plans | Missing inputs retain default-on behavior; malformed disabling inputs fail before mutation. `_get_bool_env` maps every unrecognized nonblank string to false, so it alone is insufficient for a security-relevant default-on override. Admit canonical validated values at this boundary; do not globally change unrelated boolean semantics. |
| Env binding and Job admission: `installation.runtime_inventory_gcp`, `bundle_gcp`, `engine/ecs/_env.py`, `shared.cloud.kubernetes`, GCP admission policy and its Helm counterpart | Classify any new generated values as public operator policy with correct process roles; regenerate the bundle contract. Forward exact ConfigMap values through the existing explicit environment list. Match both admission allowlists and required bindings; no `envFrom`, extra command flags, ENTRYPOINT override or weakened admission. Cover runtime-role parity and both deployment renderers. |
| Auth/IAM: `portal/iam`, `cicd-oidc-identity`, Workload Identity, `shared.range_instantiation_policy` | Keep deploy policy-management, provisioner Compute lifecycle and guest predict-only identities separate. Provider-generated network/audit logs require no new guest logging agent or credential. Readback uses a scoped operator/deploy reader; Data Access record reading requires private-log permission. Do not grant guests, portal or provisioner project IAM administration or private-log access merely for validation. Application auth/CSRF/token scopes remain at existing service boundaries; no new HTTP/admin surface is needed. |
| Provider shapes and errors: `gcp_range_cell_clients`, `gcp_range_cell_ops`, `gcp_range_cell_types`, RAES plan errors | Compute SDK bodies use snake_case proto-plus fields, unlike gcloud/REST camelCase. Validate rendered bodies with installed SDK messages, including enum/enable semantics. Only NotFound means absent; permission failures and timeouts do not. Reuse `_get_or_none`, `_wait_for_operation` and existing failure mapping/retry dispositions; no new exception hierarchy or blanket catch-and-success. |
| Host/OS exposure: `installation.contract.CommandSpec`, doctor execution seams, existing GCP readback scripts | Use fixed argv arrays with `shell=False`, validated identifiers, bounded timeouts and bounded JSON/log queries. ADC/WIF handles authentication; tokens, keys and model bodies never enter argv, command logs or shell substitution. No environment dumps, credential-bearing diagnostic URLs or raw Terraform-state artifacts. |
| Error and observability boundaries: `log_redact`, `shared.log_sanitize`, `config._logging_config`, `shared.api.errors`, operation results | Report allowlisted control names/status/settings and bounded reason codes. Fingerprint identifiers in ordinary runtime logs; keep provider payloads, principal inventories, secret references, prompts/responses and raw SDK errors out of public errors, events and metrics. Do not add a logging formatter, cloud-audit event schema or HTTP error envelope. |
| Persistence: Engine operation/ownership records and `shared.audit` | Preserve generation, placement, ownership and partial-failure evidence through existing services/repositories. Cloud Logging stores provider records; the application audit ledger stores application decisions. Do not duplicate cloud logs in PostgreSQL, add a telemetry state machine or expand provisioner database grants. |
| Repo policy/workflows | Preserve `.ground-control.yaml`, `.gc/plan-rules.md`, `.importlinter`, Terraform root validation inventory/lockfiles, `.tflint.hcl`, Checkov policy and exception registry, `_quality.yml`, `deploy.yml` and `_gcp-dev.yml`. Use canonical `Brad-Edwards/shifter`, synthetic fixtures and generic public evidence. No private pack details or new requirement/traceability records for this requirement-free issue. |

## Validation and evidence semantics

Deployment validation must report flow, NAT and Vertex controls separately,
with desired policy, observed state, applicability and coverage gaps. Evaluate
every owned subnet/gateway across actual projects/regions, including shared NAT
and configured migration bridges. For audit readback inspect effective
service-specific plus `allServices` and inherited configuration/exemptions:
a project-level override cannot disable inherited logging. Preserve unrelated
audit configuration; `google_project_iam_audit_config` is authoritative for its
service, so multiple owners or a whole-project IAM policy replacement are unsafe.
Adopt an existing service audit owner rather than competing with it, and do not
erase an existing `ADMIN_READ` entry as a side effect of adding data log types.

Reuse `installation._doctor_model` status/tier/report conventions and injected
probe boundaries. Its `ValidationCheck` executor is deliberately local and
credential-free; existing cloud health checks are HTTP probes with SSRF guards,
not an IAM/Compute inventory reader. A GCP readback needs an explicitly
cloud-read-only seam, never a cloud command hidden in local checks or an
arbitrary authenticated URL in `HealthCheck`. No ranges before deployment is
unverified/not applicable with a reason, not proof that future resources log.
Keep backend checks declared through bundle metadata; do not add a second
backend-specific checklist to the central doctor or repurpose the independent
capacity drift checker as a telemetry controller.
Disabled-by-explicit-policy is a reported coverage warning; unexpected missing
controls, invalid evidence or denied readback cannot pass. Distinguish a local
schema/render success from installed-state and actual delivery evidence.

Live record verification belongs with existing post-deploy range smoke and
operator qualification, not provision-time billing/model calls or local doctor.
The current `_gcp-dev.yml` smoke job is nonblocking; it cannot silently become
the sole hard coverage gate. Bound eventual-delivery polling, query by test
project/resource/time and authenticated caller, and keep evidence allowlisted.
Use synthetic traffic and a supported authorized model method; don't broaden
the predict-only identity to manufacture `DATA_WRITE` evidence. Test effective
write logging configuration separately when no write operation is authorized.
Do not deliberately exhaust NAT ports to create an error record.

Existing native Terraform `mock_provider`/plan assertions in `range/vpc/tests`
are the infrastructure pattern; use resource-scoped assertions for control
settings and exact project/service wiring. Existing provisioner suites
`test_gcp_range_cells`, `test_gcp_shared_nat`, `test_raes_gcp_plan` and
`test_raes_gcp_apply` are the lifecycle/renderer patterns. ADR-019 requires
testing behavior at external provider boundaries. Coverage must catch defaults,
explicit overrides, invalid inputs, SDK message construction, replay/drift,
shared enrollment/removal preserving logging, region/gateway fan-out, `none`,
missing permissions/evidence and redaction. A file-wide keyword assertion or
mocked successful deployment does not verify these acceptance criteria.

## Operator coverage and cost gotchas

Document the emitted log names:
`projects/<project>/logs/compute.googleapis.com%2Fvpc_flows`,
`projects/<project>/logs/compute.googleapis.com%2Fnat_flows`, and
`projects/<project>/logs/cloudaudit.googleapis.com%2Fdata_access`
(Vertex filter `protoPayload.serviceName="aiplatform.googleapis.com"`).
The existing `portal/gcs` **GCS** `audit_logs` bucket is for Storage usage logs;
it is not a Cloud Logging log bucket or a route for these records. Likewise,
the required Admin Activity log bucket's retention does not cover Data Access.
Report effective sinks/exclusions, destinations, retention and read permission;
do not silently overwrite organizational routing, create duplicate storage or
claim 30 days is guaranteed on an operator-modified project.

Flow records have primary packet sampling plus the selected secondary sampling;
even `1.0` does not promise a complete packet history. NAT logging has provider
rate limits/omissions; `ALL` is both record categories, not every packet/error.
Absence of records is not evidence of absence of traffic. Vertex audit coverage
is method-dependent; qualify the actual supported prediction/streaming methods,
caller identity and target resource fields. A shared service-account principal
does not identify a human participant or uniquely identify a range. Success and
permission-denied reads can have different identity-redaction behavior.

Treat full metadata and audit resource/caller fields as sensitive operational
data. Restrict access and exports; provider audit configuration is not an opt-in
to Vertex request/response logging. Do not persist prompts or completions in
application diagnostics or enable body logging to fill audit gaps.

Cost guidance must include network-log generation plus Logging storage, Vertex
Data Access volume, extended retention and destination charges. Five-second
aggregation and all metadata favor investigation; `0.5` reduces retained flow
volume. NAT `ALL` increases volume relative to errors-only. Do not claim logging
is free under the general Logging allowance: vended network logs have separate
pricing. Use current provider pricing and observed bytes, not a fixed per-range
cost or a promise that sampling reduces every billing component.

Provider references checked for this preflight: [flow sampling](https://docs.cloud.google.com/vpc/docs/flow-logs),
[NAT limitations](https://docs.cloud.google.com/nat/docs/monitoring),
[Vertex audit methods and permissions](https://docs.cloud.google.com/vertex-ai/docs/general/audit-logging),
[audit inheritance](https://docs.cloud.google.com/logging/docs/audit/configure-data-access),
[Logging routing, retention and pricing](https://cloud.google.com/products/observability/pricing),
and [Terraform IAM audit ownership](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/google_project_iam).
Provider references are guidance, not live qualification evidence.

## Non-goals

No issue implementation in this preflight. Subsequent delivery is GCP native
telemetry defaults, explicit operator coverage overrides, validation, targeted
tests and operator documentation. No AWS expansion, broker/gateway revival,
spend enforcement, guest agents, traffic-policy change, scenario schema changes,
new public API, cloud-log ingestion service, compliance archive/retention lock,
SIEM pipeline, blanket historic-range migration or new lifecycle/repository
abstraction. Owned replay must converge; remediation of unrelated historical
resources requires an explicit operator procedure rather than indiscriminate
discovery and mutation.
