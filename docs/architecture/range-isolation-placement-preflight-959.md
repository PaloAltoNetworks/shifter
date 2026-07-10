# Range Isolation And Placement ADR Preflight (#959)

Status: pre-implementation guidance

Date: 2026-06-15

Tracking issue: GitHub #959, "network: document range isolation and single-AZ
placement as ADRs".

This is a requirement-free preflight. The issue body is the shipping contract:
record the AWS range isolation model and the single-AZ placement decision as
ADRs, including blast-radius rationale and any explicit decision to change
placement. This note is not itself the ADR and does not implement the issue.

## Architecture Decisions

- Keep the two decisions separate. The isolation model is a reachability and
  inspection decision: per-range security groups intentionally allow broad
  outbound traffic while internet egress is forced through AWS Network
  Firewall default-deny policy. Single-AZ placement is a failure-domain,
  capacity, and cost decision: stable range infrastructure and runtime range
  subnets are currently pinned to one AZ.
- Reuse the existing range egress vocabulary from ADR-017 and
  `docs/architecture/range-egress-ip-allowlist.md`. Do not create a second
  "range isolation" schema for CIDR/domain allowlists, and do not rename the
  public `settings.range_egress` contract while documenting the current AWS
  posture.
- The ADR should document the live AWS model before recommending changes:
  `enable_network_firewall = true` sends user-subnet 0/0 traffic to the
  firewall endpoint; the stateful policy allows NGFW bypass when enabled,
  victim CIDR/domain lanes, optional Kali domains, DNS, NTP, then drops all
  unmatched egress.
- The ADR should also document the explicit opt-out hazard:
  `enable_network_firewall = false` routes private traffic to NAT directly.
  If future work makes the firewall optional in a production profile, that is a
  policy change and needs its own guardrail.
- For single-AZ placement, prefer documenting the current decision unless the
  issue is explicitly expanded to implement multi-AZ. A real multi-AZ range
  design would affect stable range VPC subnets, runtime subnet placement,
  Network Firewall endpoint mapping, NAT routing, S3/SSM endpoint placement,
  engine-provisioner environment variables, IAM conditions, and tests.
- Multi-AZ placement, if later warranted, needs a provider-neutral placement
  seam such as an ordered zone list plus a per-range placement selector. It
  should not be introduced as ad hoc use of `data.aws_availability_zones` in
  the runtime module only.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #959 |
| --- | --- | --- |
| ADR registry | `docs/adr/index.yaml`, `docs/adr/README.md`, `docs/adr/exceptions.yaml` | Add accepted decision records through the machine-readable ADR registry. If a new enforceable rule or exception is added, update evidence and exception metadata there. |
| ADR enforcement | `scripts/adr_guard/adr_guard.py`, `.gc/plan-rules.md`, `shifter/shifter_platform/documentation/docs/technical/dev/adr-enforcement.md` | ADR/guardrail-file changes must pass `adr_guard`; new enforcement belongs in `adr_guard`, not prose only. |
| Range egress decision | ADR-017 in `docs/adr/index.yaml`, `docs/architecture/range-egress-ip-allowlist.md`, `shifter/installation/range_egress.py` | Extend or reference this contract for egress policy language instead of duplicating CIDR/domain schema or validation rules. |
| AWS range VPC | `platform/terraform/modules/range/vpc/{main,nat,firewall,variables,outputs}.tf`, env roots under `platform/terraform/environments/{dev,prod}/range/` | These own stable VPC, default SG lockdown, NAT, Network Firewall, S3/SSM endpoints, outputs, and current `local.primary_az`. |
| Runtime range module | `shifter/engine/provisioner/terraform/modules/range/{variables,main,outputs}.tf` | Per-range subnets, per-subnet SGs, routes, and EC2 placement are runtime Terraform, not stable platform Terraform. |
| Env binding | `platform/terraform/modules/engine-provisioner/task_definition.tf`, `platform/terraform/environments/{dev,prod}/portal/main.tf`, `shifter/engine/provisioner/config.py`, `terraform_vars.py` | Range VPC outputs flow into the provisioner as `RANGE_VPC_*`, `RANGE_AVAILABILITY_ZONE`, and `FIREWALL_ENDPOINT_ID`. Preserve the contract unless the ADR explicitly records a migration. |
| IAM placement guard | `platform/terraform/modules/engine-provisioner/iam.tf` | `ec2:RunInstances` volume creation is constrained to `var.range_availability_zone`; multi-AZ changes must update IAM intentionally. |
| Live networking docs | `shifter/shifter_platform/documentation/docs/technical/platform_infrastructure/networking.md` | User-facing platform docs should match the ADR once the ADR lands. Deprecated docs are not the source of truth. |

## Cross-Cutting Layers

- Auth surface: the ADR should not change Cognito/OIDC, CTF participant auth,
  terminal access auth, or Guacamole broker behavior. Range reachability from
  the portal remains the existing peering plus SSH/RDP path.
- Secret-handling surface: CIDRs, AZ names, subnet IDs, route table IDs,
  firewall endpoint IDs, and ADR text are non-secret configuration. Do not move
  them into Secrets Manager, SSM SecureString, Kubernetes Secrets, or runtime
  secret env vars. Existing SSH keys and guest passwords remain in the current
  Secrets Manager paths.
- Env-binding shape: keep range placement and firewall endpoint data flowing
  through Terraform outputs into typed module variables and task env vars. Do
  not add a parallel YAML parser, Django setting, or workflow variable for the
  ADR-only change.
- Terraform validation and policy gates: stable range VPC changes must keep
  Terraform typing/validation, Checkov exceptions, TFLint, and `adr_guard`
  intact. If new Checkov skips appear, they require `docs/adr/exceptions.yaml`
  entries with owner and expiry.
- Routing/security policy: per-range SG all-egress is acceptable only because
  route tables send 0/0 to the firewall endpoint and the firewall policy drops
  unmatched egress. Document that SGs decide local reachability while Network
  Firewall owns internet egress filtering; do not claim SGs enforce cross-range
  internet isolation.
- OS/process exposure: an ADR-only change should not add shell commands. If a
  future migration script is added, use existing argv-array subprocess patterns
  and keep credentials out of process arguments.
- Error envelope: expected failures for future infrastructure changes should
  surface through Terraform validate/plan/apply, Checkov/TFLint, and ADR guard.
  Do not add Django exceptions, API DTOs, repositories, or user-facing error
  envelopes for a documentation-only ADR.
- Observability/logging: Network Firewall FLOW/ALERT logs and optional VPC flow
  logs are the evidence surfaces. Do not make application logs the source of
  truth for range isolation.

## Extensibility Seam

The immediate seam is documentation plus existing Terraform outputs. The next
reasonable change is multi-AZ placement. That needs an environment-owned zone
list and a per-range placement selector that can feed both stable range
infrastructure and runtime range Terraform. It must also return firewall
endpoint IDs by AZ or otherwise define a deterministic route target for each
runtime subnet. Avoid a boolean `multi_az` flag without an explicit placement
contract; it will hide routing, endpoint, IAM, and capacity semantics behind a
single overloaded knob.

## Gotchas And Anti-Patterns

- Do not conflate AWS Network Firewall, persistent VM-Series NGFW, portal VPC
  inspection, security groups, GCP VPC firewall rules, Kubernetes
  NetworkPolicy, and Cyberscript `connected_to`. They are distinct layers.
- Do not treat `connected_to` as cross-range or participant isolation. It is a
  scenario topology contract for within-range subnet reachability.
- Do not document "all-egress SGs are safe" without the matching route-table
  and Network Firewall default-deny dependency.
- Do not change `enable_network_firewall`, firewall rule order, DNS/NTP lanes,
  NGFW bypass, NAT routing, or endpoint outputs as part of the ADR-only issue.
- Do not copy the portal per-AZ inspection design into the range VPC by
  analogy. Portal inspection has ALB cross-zone and east-west visibility goals;
  range egress has per-range runtime subnet placement and default-deny egress
  goals.
- Do not rely on the stale `docs/architecture/gcp-vpc-firewall-preflight.md`
  issue-number reference for this work. Use the current issue title/body and
  acceptance criteria as the contract.
- Do not add a changelog fragment for a pure ADR/preflight-only change unless
  the final PR makes a user-visible documentation release note worthwhile.

## Non-Goals

- No Terraform implementation, runtime placement change, SG rule change,
  firewall policy change, NAT/endpoint redesign, or multi-AZ migration.
- No root `shifter.yaml` schema change, installation parser change, Django
  setting, service, model, DTO, API, repository, exception hierarchy, or logging
  framework.
- No GCP, Kubernetes, Helm, GDC, portal VPC inspection, or persistent VM-Series
  NGFW implementation.
- No new ADR guard unless the implementation introduces a new enforceable rule.
- No Ground Control requirement or traceability work; this run is
  requirement-free and the GitHub issue is the contract.

## Validation Expectations

For the ADR implementation that follows, run:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
```

If the implementation touches Terraform or workflows despite the ADR-only
scope, also run the stack-native validators required by `.gc/plan-rules.md` for
those touched surfaces.
