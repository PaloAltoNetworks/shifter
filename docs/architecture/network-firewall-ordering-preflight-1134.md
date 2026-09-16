# Network Firewall Ordering Preflight (#1134)

Status: pre-implementation guidance

Date: 2026-08-14

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1134>

## Scope Boundary

This is a requirement-free architecture preflight. GitHub issue #1134 is the
shipping contract: an ordinary range-egress allowlist shrink and either portal
inspection toggle direction must converge in one normal saved-plan Terraform
apply without manual AWS API or state surgery.

This note does not implement the issue. The implementation stays inside the
existing AWS Terraform, configuration-rendering, validation, deploy, and live
assertion boundaries. It must not change range-egress policy semantics or the
portal inspection topology merely to avoid an ordering failure.

## Repository Findings

- `platform/terraform/modules/range/vpc/firewall.tf` makes
  `aws_networkfirewall_rule_group.victim_ips` cardinality equal the number of
  300-CIDR chunks and dynamically references every instance from one firewall
  policy. Shrinking the list therefore combines an in-place policy update with
  destruction of trailing rule-group instances.
- The existing implicit policy-to-rule-group dependency is sufficient for full
  creation/destruction, but it has not serialized the policy's in-place
  dereference ahead of destruction of removed collection instances. Repeating
  that same edge with `depends_on` does not create a new lifecycle boundary.
- The chunking comment conflates a per-rule limit with resource cardinality.
  AWS limits each expanded Suricata rule to 8,192 characters, while a rule
  group can carry multiple rules in a much larger rules string. CIDR chunks can
  therefore remain separate rule variables/rules inside one stable rule group;
  they do not need separate rule-group resources.
- `platform/terraform/modules/portal/vpc/main.tf` and `inspection.tf` already
  make the direct-NAT and firewall-endpoint defaults logically exclusive, but
  two `aws_route` resource addresses still claim the same
  `(route_table_id, 0.0.0.0/0)` AWS object. Terraform consequently schedules a
  create/destroy transition where the EC2 API supports changing the existing
  route's target with `ReplaceRoute`.
- `scripts/assert_portal_inspection` proves the inspection-on topology after
  apply, but intentionally returns without querying AWS when inspection is
  off. It therefore does not currently prove the NAT-owned result of a
  true-to-false transition.
- Portal VPC module contracts already run through
  `platform/terraform/modules/portal/vpc/tests/`. The range VPC module is still
  marked `contract: deferred` in
  `platform/terraform/validation-inventory.yaml`; issue #1134 is a suitable
  boundary for adding its first credential-free Terraform contract test.

## Architecture Decisions And Guardrails

### Range victim-IP rules: stable group identity

- Keep CIDR chunking as a provider-local rendering detail, but place all chunks
  in one stable stateful rule group. Define one IP-set variable and one HTTPS
  pass rule per chunk inside that group. The rule-group resource count must not
  vary with `length(local.cidr_chunks)`.
- Keep that rule group present whenever the range Network Firewall is present,
  including an empty allowlist. The empty representation must be a valid,
  non-permitting rule (for example, an alert-only rule that cannot create an
  allow lane). Never use a broad or reserved-address `pass` rule as an empty
  sentinel.
- Preserve the existing `RangeEgressPolicy` meaning, TCP/443-only IP allow
  lane, STRICT_ORDER relationships, fixed rule-group capacity, KMS encryption,
  tags, firewall FLOW/ALERT logging, NTP/domain lanes, and priority-100 default
  drop. Consolidation is lifecycle normalization, not a policy change.
- The migration from the current multi-group state must create a policy object
  that can coexist with the old policy, switch the firewall to it, and remove
  the old policy before old trailing rule groups become destroyable. A policy
  replacement using a coexistable unique name plus
  `create_before_destroy` is an acceptable Terraform-native expression of this
  boundary, but the saved plan and a live proof transition must demonstrate the
  actual order.
- `create_before_destroy` on `victim_ips` alone is not a fix: it changes
  replacement order but does not turn an instance removed by a count shrink
  into a replacement. A second apply, `-target`, AWS CLI dereference, cleanup
  hook, destroy-time provisioner, retry sleep, or routine orphan sweeper is also
  not an acceptable steady-state lifecycle.

### Portal private default: one Terraform owner

- Model each private route table's IPv4 default as one persistent `aws_route`
  resource. Its count is controlled only by `enable_nat_gateway`; exactly one
  of `nat_gateway_id` and `vpc_endpoint_id` is non-null according to
  `enable_portal_inspection`.
- Keep the resource at the portal VPC boundary. The inspection file may provide
  the per-AZ endpoint map, but it must not own a second default-route object.
  Do not mix standalone `aws_route` resources with inline routes on the same
  route table.
- Preserve existing state in both starting modes. Because two historical
  addresses converge on one new address, use a moved-block chain through one
  historical address; two independent moves directly to the same destination
  are ambiguous to Terraform. The reviewed plan must show address moves plus
  in-place route target changes, not route creation before deletion.
- Continue using the existing `enable_portal_inspection` boolean. Do not add a
  route-owner enum, duplicate feature toggle, workflow variable, or generic
  routing DSL for a two-target choice.
- Extend the existing post-apply assertion rather than adding a second script.
  Inspection-on keeps its endpoint and no-NAT-bypass checks. Inspection-off
  must describe the private route tables and require one active
  `0.0.0.0/0 -> nat_gateway_id` route with no endpoint target or blackhole.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1134 |
| --- | --- | --- |
| Public range-egress schema | `shifter/installation/range_egress.py`, `loader.py`, `errors.py` | Keep `settings.range_egress`, `RangeEgressPolicy`, CIDR normalization, mode invariants, and `InstallationConfigError`; add no schema or validator. |
| AWS range bridge | `shifter/installation/render.py`, `.github/workflows/_range.yml`, environment range `variables.tf`/`main.tf` | Continue rendering `victim_allowed_cidrs.auto.tfvars` from normalized root config. Provider bridge names stay internal. |
| Direct-Terraform CIDR validation | `platform/terraform/modules/range/vpc/variables.tf` | Keep the existing canonical CIDR, no-/0, no-host-bits, no-duplicates validation as the direct-use backstop. |
| Range firewall policy | `platform/terraform/modules/range/vpc/{firewall,kms,variables}.tf`, ADR-017, `range-egress-ip-allowlist.md` | Preserve STRICT_ORDER, KMS, logging, default drop, and the separate domain/IP/NTP/NGFW lanes. |
| Portal route ownership | `platform/terraform/modules/portal/vpc/{main,inspection}.tf` | Keep private route tables in the VPC module and converge the default destination to one route resource. |
| Portal live proof | `scripts/assert_portal_inspection/`, environment portal `outputs.tf`, `_shifter-platform.yml` | Extend the typed non-secret contract and injected-runner tests; retain bounded `::error::` diagnostics and the existing post-apply position. |
| Terraform state refactors | Existing `moved.tf` files and moved-block chains under platform modules | Use declarative moved blocks; no `terraform state mv`, import, state removal, or address-breaking rename in normal deployment. |
| Terraform validation | `platform/terraform/validation-inventory.yaml`, module `tests/*.tftest.hcl`, root validation matrix | Add behavioral module contracts to the already canonical `terraform test` surface rather than relying on an unwired text-only test. |
| Deploy workflow | `_range.yml` and `_shifter-platform.yml` saved-plan applies, GitHub OIDC/environment roles | Keep plan/apply inputs identical, state locking, environment gates, and existing role assumption. Do not insert a targeted pre-apply. |
| Orphan recovery | `scripts/bootstrap/account_recovery.py` `NetworkFirewallRuleGroupHandler` | Leave asynchronous orphan cleanup as recovery only; it must not become part of a normal policy update. |
| IaC enforcement | `.tflint.hcl`, `platform/terraform/.checkov.yaml`, `scripts/check_tf_roots`, ADR guard | Preserve blocking lint/security/validation. New skips still require an ADR-004-R11 exception with owner and expiry. |

No controller, DTO, service, repository, database, application exception, or
runtime persistence incumbent applies. Terraform state and the AWS control
plane remain the only lifecycle owners in scope.

## Cross-Cutting Layers The Design Must Pass

- **Authentication and authorization:** no Cognito, Django, ALB listener, CTF,
  participant, or operator-auth contract changes. CI continues to use the
  existing GitHub OIDC environment role. A verifier may use only the deploy
  role's existing read access to Network Firewall and EC2 route-table state; do
  not add static cloud credentials or broaden application roles.
- **Secret handling:** CIDRs, route-table IDs, endpoint IDs, NAT IDs, policy
  ARNs, and rule-group ARNs are non-secret operational configuration.
  `shifter.yaml` still receives sensitive handling because it can contain secret
  references: `_range.yml` writes it to the runner temp directory and passes
  only file paths to `shifter-config render`. Do not print the file, rendered
  tfvars, credentials, SSM/Secrets Manager values, or raw Terraform state.
- **Environment binding:** `enable_portal_inspection` remains a typed portal
  root/module boolean; `settings.range_egress` remains the provider-neutral
  root shape; `victim_allowed_cidrs` remains the generated AWS bridge. Existing
  strict active-environment selection in `_range.yml` and whole-file
  `TF_VARS_<ENV>_*` overlays remain unchanged.
- **Validation layers:** root config must pass the installation loader's
  duplicate-key/merge-key/backend/settings/secret-reference checks and
  `RangeEgressPolicy`; direct Terraform use must pass module variable
  validation; portal topology must retain the `az_count` bound and
  `enable_portal_inspection => enable_log_aggregation` precondition; every
  route must present exactly one provider target. TFLint, Checkov, root
  validation, module contracts, and ADR guard remain separate mandatory gates.
- **Routing and security policy:** the route-target update must retain one
  default route per private table. Inspection-on still routes to the same-AZ
  firewall endpoint and then same-AZ NAT; inspection-off routes directly to the
  existing NAT. Security groups remain reachability gates and Network Firewall
  remains inspection/egress enforcement; neither substitutes for the other.
- **OS/process exposure:** the Terraform-only change needs no new subprocess.
  If the live assertion changes, retain argv-list `subprocess.run`, executable
  discovery, in-memory JSON parsing, sanitized diagnostics, and no shell or
  secret-bearing argv from `scripts/assert_portal_inspection`.
- **Error envelope and observability:** configuration errors stay
  `InstallationConfigError`; infrastructure errors stay Terraform/provider
  errors; live route mismatches stay bounded GitHub `::error::` records with a
  nonzero exit. Keep existing KMS-backed Network Firewall FLOW/ALERT logs and
  portal log aggregation. Do not add a Django error type, raw AWS response
  dump, parallel log group, alarm framework, or notification path.
- **Persistence and ownership:** generated bridge tfvars are ephemeral;
  Terraform remote state owns resource addresses; AWS owns live readiness.
  Declarative moved blocks reconcile state identity. Manual API mutation, state
  editing, imports, and cleanup sweeps are not persistence mechanisms for this
  transition.

## Extensibility View

- The range seam is `local.cidr_chunk_size` plus a data-driven collection of
  IP-set variables/rules *inside one group*. A larger or smaller allowlist adds
  or removes rules without adding policy references or Terraform resource
  instances. Keep this provider-limit seam local; do not expose chunk size in
  `shifter.yaml` or environment tfvars.
- The portal seam is the single private-default resource parameterized by the
  existing inspection boolean and per-AZ endpoint/NAT collections. Another
  environment or AZ count reuses the same resource expression. A genuinely new
  target type should extend this one owner with a typed module input only when
  that requirement exists, not pre-emptively through a route abstraction.
- Keep stable physical/resource identities independent of collection size.
  Future allowlist modes or inspection policy changes may alter content, but
  should not reintroduce resource cardinality as an ordering protocol.

## Whole-Repository Surfaces In Scope

Expected implementation surfaces:

- `platform/terraform/modules/range/vpc/firewall.tf`
- `platform/terraform/modules/range/vpc/tests/` and
  `platform/terraform/validation-inventory.yaml`
- `platform/terraform/modules/portal/vpc/main.tf`
- `platform/terraform/modules/portal/vpc/inspection.tf`
- a portal VPC `moved.tf` and `tests/*.tftest.hcl` if those concerns are kept
  separate
- `scripts/assert_portal_inspection/assert_portal_inspection.py` and its tests
- `docs/architecture/range-egress-ip-allowlist.md` where it currently warns
  about manual rule-group cleanup

Comparison and validation surfaces that should normally remain unchanged:

- `shifter/installation/{range_egress,render,loader,errors}.py` and their tests
- `platform/terraform/environments/{dev,proof,prod}/{range,portal}/` except a
  typed assertion output only if the current contract lacks required data
- `.github/workflows/{_range,_shifter-platform}.yml`
- `scripts/bootstrap/account_recovery.py`
- `docs/adr/index.yaml` ADR-017 and ADR-026
- Network Firewall KMS, logging, delete-protection, subnet, SG, NAT, and
  log-aggregation resources

## Gotchas And Anti-Patterns

- A clean first apply is not regression evidence. Exercise an existing live
  state with more than one CIDR chunk, then a one-chunk and empty-list policy,
  and exercise portal false-to-true-to-false. Each transition must complete in
  one saved-plan apply and a following plan must be empty.
- Mock-provider tests prove expressions and resource cardinality, not AWS
  propagation or delete constraints. The reproduced proof-tenant transition is
  required acceptance evidence for the policy migration.
- Do not assume `depends_on` forces an otherwise in-place dependent resource to
  update, or that it creates a destroy-before-create edge between two siblings.
- Do not use `create_before_destroy` on fixed-name rule groups; replacement
  requires two names to coexist and pure removals are not replacements.
- Do not keep two counted `aws_route` blocks and try to order them with
  `depends_on`, sleeps, or `-parallelism=1`. They still represent one AWS object
  with competing Terraform identities.
- Do not use two direct moved blocks with the same destination. Use a chain and
  inspect plans from both historical starting states.
- An EC2 route-target replacement can interrupt existing connections even when
  it avoids `RouteAlreadyExists`; do not promise zero-downtime sessions for an
  inspection topology toggle.
- Portal inspection delete protection remains a separate lifecycle contract.
  An environment with protection enabled must deliberately converge that
  existing boolean before deleting the firewall; #1134 must not silently
  disable the protection or overload the inspection toggle.
- Inspection toggling also changes NAT cardinality (one shared NAT when off,
  per-AZ NATs when on). Preserve index/AZ mapping and the existing assertion;
  fixing the private default route must not collapse that topology.
- Do not change IP/domain/NTP evaluation order, convert alert-only portal
  inspection to drop-by-default, widen any allowlist, or weaken default-deny to
  make transition testing pass.
- Do not introduce prefix lists, a second policy language, a generic firewall
  module, a new renderer, a workflow-local YAML parser, or a normal-path orphan
  cleanup command for this lifecycle-only defect.
- CI pins Terraform 1.13.3 even if a developer workstation is newer. Do not use
  lifecycle/action features unavailable in the pinned toolchain.

## Non-Goals And Implementation Boundaries

- No implementation in this preflight note.
- No change to public `settings.range_egress` modes, CIDR validation,
  normalization, generated bridge names, scenario overrides, RBAC, API, or UI.
- No change to portal firewall rules, east-west scope, asymmetric-flow
  trade-off, ALB/target security groups, log aggregation, NAT availability
  model, or portal-to-range peering.
- No new AWS prefix-list/resource-group dependency, third-party firewall,
  VM-Series topology, secret, IAM role, database state, DTO, controller,
  service, repository, exception hierarchy, or logging framework.
- No GCP, Kubernetes, Helm, application runtime, image, Packer, or bootstrap
  implementation.
- No manual AWS CLI repair, targeted apply, state command, import, destroy
  workflow, Checkov skip, ADR exception, or CI weakening as the shipped fix.

## Validation Expectations

The implementation must run the repository and Terraform-native gates for the
touched surfaces:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run `terraform fmt`, backendless `terraform validate` for dev/proof/prod
range and portal roots, the portal and range VPC `terraform test` suites, the
focused `scripts/assert_portal_inspection` tests, and Checkov through the
repository-standard path. Run `actionlint` only if a workflow is changed. Live
proof acceptance must capture saved plans and post-apply AWS state without
printing rendered deployment configuration or credentials.
