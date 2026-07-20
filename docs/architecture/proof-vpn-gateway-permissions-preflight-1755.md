# Proof VPN Gateway Permissions Preflight

Issue: GitHub #1755, "Fix proof provisioner permissions for per-range VPN
gateways."

This is requirement-free architecture guidance. The issue is the shipping
contract. The change is a least-privilege repair to the existing AWS OpenVPN
realization plus a terminal-state correction in the existing post-deploy smoke;
it does not introduce another gateway, range lifecycle, or smoke workflow.

## Decision Boundary

The request-owned OpenVPN stack from ADR-039-R9 and #1695 remains canonical.
Its AWS realization is
`shifter/engine/provisioner/terraform/modules/range/vpn.tf`; its control-plane
identity is the existing engine-provisioner ECS task role in
`platform/terraform/modules/engine-provisioner/iam.tf`; and every generated
gateway role receives the existing installation boundary through
`RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN`.

The proof failure is policy parity drift, not a reason to widen that contract:

- the task role already has a VPN role-management identity policy, but the
  shared `ci_role_permissions_boundary` blanket IAM deny carves out only the
  Polaris-agent role namespace;
- an effective boundary exception must cover both the exact per-range gateway
  **role** and **instance-profile** namespaces, because Terraform creates,
  associates, disassociates, and destroys both resource types;
- the ELB identity policy contains `CreateListener`, but its request-tag
  condition is not satisfied unless `aws_lb_listener.vpn` sends the standard
  range ownership tags in the `CreateListener` request; and
- the current ELB checker conflates GWLB and request-owned NLB resources. That
  model must become resource/action aware rather than forcing a broad common
  statement or weakening the pre-existing GWLB controls.

AWS authorizes `CreateListener` against the parent `loadbalancer/net/...` ARN,
supports request-tag conditions, and treats `AddTags` as a dependent action.
The API accepts listener tags in the create request. The implementation must
therefore tag the listener at creation, authorize the exact NLB parent name,
and require the standard ownership resource tags on that parent. It must not
solve this by removing ownership conditions or using `Resource = "*"`.

References:

- <https://docs.aws.amazon.com/service-authorization/latest/reference/list_awselasticloadbalancingv2.html>
- <https://docs.aws.amazon.com/elasticloadbalancing/latest/APIReference/API_CreateListener.html>

## Architecture Decisions And Guardrails

### IAM delegation

- Extend the incumbent permissions-boundary delegation pattern in
  `platform/terraform/global/iam/github-oidc.tf`; do not add another boundary or
  attach a grant policy to the boundary. The blanket `DenyIamEscalation`
  `NotResource` exception may add only these environment-scoped namespaces:
  `role/shifter-${var.environment}-*-vpn-gateway` and
  `instance-profile/shifter-${var.environment}-*-vpn-gateway`. Preserve the
  existing Polaris-agent exception unchanged.
- Add the gateway equivalent of `DenyPolarisAgentBoundaryTamper` for
  `iam:PutRolePermissionsBoundary` and
  `iam:DeleteRolePermissionsBoundary` on the exact VPN role namespace. The
  task-role identity policy must continue to have neither action.
- Keep `CreateRole` conditioned on the exact
  `var.permissions_boundary_arn`. Keep all management actions enumerated and
  resource-scoped to the environment's VPN role or instance-profile namespace.
  Keep `AttachRolePolicy` / `DetachRolePolicy` limited to
  `AmazonSSMManagedInstanceCore`, and keep `PassRole` limited to the gateway
  role namespace with `iam:PassedToService = ec2.amazonaws.com`.
- Effective permission is deliberately the intersection of the boundary and
  `aws_iam_role_policy.vpn_gateway_role_management`. The boundary namespace
  carve-out alone is not a grant and must never be treated as sufficient
  authorization in a regression test.

### ELBv2 authorization

- Keep the existing customer-managed engine-provisioner ELB policy and its
  attachment; issue #1749 moved it out of the inline-policy budget. Do not add a
  new managed-policy attachment or rename the deployed policy for this repair.
- Split policy reasoning by action and resource type. The VPN NLB names are
  already centralized by the runtime module as `shifter-vpn-${range_id}-...`.
  NLB load balancer, target group, and listener ARN patterns must use that
  prefix, the account, region, and environment ownership tags. Existing GWLB
  ARN paths and controls remain unchanged.
- Add `local.common_tags` to `aws_lb_listener.vpn`, as already done for the VPN
  load balancer and target group. Creation statements retain the standard
  `aws:RequestTag` gates. The `CreateListener` statement additionally requires
  the standard `elasticloadbalancing:ResourceTag` gates on its parent NLB;
  existing-resource mutation statements retain those same resource-tag gates.
  Preserve `AddTags` as a separately scoped, create-action-conditioned
  statement.
- Do not add listener-rule, certificate, TLS, ALB, cross-zone, or unrelated ELB
  permissions. The runtime creates one UDP listener with one forward action;
  only its provider-observed create/read/delete/tag dependencies are in scope.
- Update `scripts/check_tf_iam_elb_scope` rather than adding a second ELB policy
  checker. It must retain the #46 GWLB assertions and separately pin the VPN
  NLB ARN/tag/listener contract, including the runtime listener's
  creation-time tags. Update both the checker tests and its existing
  pre-commit/CI invocation inputs if the runtime `vpn.tf` file becomes a checked
  input.

### Smoke terminal state

- `shared.enums.ResourceStatus` and `TERMINAL_STATUSES` are the sole lifecycle
  schema. `run_post_deploy_smoke` must continue polling through non-terminal
  states, return on `READY`, and immediately raise the existing Django
  `CommandError` when the projected CMS status is any canonical terminal state
  (`FAILED` or `DESTROYED`). Do not add a smoke-local terminal list or import a
  private Engine lifecycle helper.
- Continue reading through the public `cms.services` facade:
  `find_range_instance_id_by_request` followed by
  `get_range_status_by_id`. Do not query ORM rows directly or poll Engine as a
  second authority.
- Report only the bounded canonical status and request UUID. Do not fetch or
  serialize the provisioner's raw Terraform/AWS error, stored error text,
  secret references, endpoint, or profile material into the command error.
- Preserve `handle()`'s primary-failure/`finally` cleanup behavior. A terminal
  provisioning failure still calls the canonical
  `destroy_range_by_request_id`; cleanup failure is logged separately and must
  not replace the terminal-state failure.
- Add focused behavior tests beside the existing management-command tests.
  Cover `FAILED` and the other canonical terminal state, assert no subsequent
  sleep/poll occurs, assert the status is present in the `CommandError`, and
  assert request-id cleanup still runs. Keep the existing fast-clock and
  service-boundary mocking conventions.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Required reuse |
| --- | --- | --- |
| OpenVPN infrastructure | `shifter/engine/provisioner/terraform/modules/range/vpn.tf`, `local.common_tags`, existing `shifter-vpn-*` names | Correct tags/authorization only; do not create another VPN module or naming schema. |
| Provisioner identity | `platform/terraform/modules/engine-provisioner/iam.tf::vpn_gateway_role_management` and the existing managed `gwlb` policy | Extend the enumerated, resource-scoped statements in place. |
| Boundary delegation | `platform/terraform/global/iam/github-oidc.tf::ci_role_permissions_boundary`, Polaris namespace carve-out/tamper-deny pattern | Add exact VPN role and instance-profile namespaces while retaining boundary tamper denial. |
| Runtime binding | Portal root `permissions_boundary_arn` -> engine-provisioner task definition -> `RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN` -> `terraform_vars` -> `vpn_gateway_permissions_boundary_arn` | Reuse the existing non-secret ARN binding; no new setting, tfvar, or environment variable. |
| Lifecycle schema | `shared.enums.ResourceStatus` and `TERMINAL_STATUSES` | One status vocabulary for persistence, projection, polling, and error reporting. |
| Smoke orchestration | `run_post_deploy_smoke`, `cms.services`, `scripts/smoke-test.sh`, `portal_deploy.py run-manage-on-portal` | Correct the one canonical readiness loop; keep request-id ownership and cleanup. |
| IAM/ELB enforcement | `scripts/check_tf_iam_elb_scope`, `scripts/check_tf_iam_role_naming`, their unittest modules, existing pre-commit and `_quality.yml` steps | Extend the incumbent checks; do not create parallel lint frameworks or CI-only checks. |
| Errors/logging | Django `CommandError`, the command's `logger`, `shared.log_sanitize`, provisioner `log_redact` | Emit fixed, bounded status diagnostics; do not cross the provider-error or secret boundary. |

## Cross-Cutting Security And Validation Layers

1. **Terraform policy shape.** The global boundary and task identity policy are
   separate policy evaluators and both must allow the call. Static tests must
   prove the exact role and instance-profile namespaces, mandatory boundary on
   `CreateRole`, boundary-tamper deny, SSM policy allowlist, and EC2-only
   `PassRole`; a text assertion that merely finds `iam:CreateRole` is vacuous.
2. **ELB authorization shape.** Action-specific resource types matter:
   `CreateListener` is checked against the NLB ARN, while delete/tag operations
   use the created listener ARN. The create request carries `local.common_tags`,
   satisfying the request-tag condition and the dependent `AddTags` permission;
   the parent NLB satisfies the listener statement's resource-tag conditions,
   and later mutations satisfy resource-tag conditions on the created resource.
3. **Provider/runtime Terraform validation.** Existing
   `openvpn_capability_target` and `openvpn_capability_prerequisites` checks keep
   capability version, single target, edge subnet, boundary ARN presence,
   provider endpoint, and portal CIDR fail-closed before resource creation.
   The repair must not bypass or duplicate them.
4. **Environment binding.** The boundary ARN is constructed from the current
   account/environment in each Portal root, typed by the engine-provisioner
   module, placed in the ECS task environment, and forwarded to the range
   module. It is a non-secret policy reference. No user-, scenario-, HTTP-, or
   workflow-supplied free-form value is introduced.
5. **Secret handling.** No certificate, key, OpenVPN profile, secret value, or
   new secret reference crosses this change. The gateway's existing inline
   policy remains limited to its generation-specific server secret and KMS
   decrypt through Secrets Manager. Terraform state/plan gains no secret input.
6. **OS/process exposure.** No new argv, shell, user-data, file, or process
   environment surface is needed. Existing Terraform staging keeps generated
   tfvars owner-only and purges them; the policy ARN is non-secret. Do not pass
   IAM JSON or profile material on a shell command line.
7. **Persistence and service boundary.** The smoke reads the existing CMS
   projection and uses canonical CMS destroy. It adds no status column, DTO,
   repository, event, polling table, or Engine/CMS dual read.
8. **Error envelope and observability.** The operator receives a non-zero
   `CommandError` containing only the canonical terminal status and request
   UUID. Existing logs retain stack/correlation context and cleanup logging;
   provider payloads and stored error messages stay behind provisioner
   redaction. IAM/ELB denial evidence belongs in CloudTrail/Terraform logs, not
   a new application error schema.
9. **Repository enforcement.** Terraform formatting/validation, TFLint,
   Checkov, the ELB/IAM focused checker suites, and ADR guard remain blocking.
   Because this changes a guardrail file and the meaning of an existing IAM
   checker, the implementation must update the ADR enforcement registry/docs
   in the same change rather than silently broadening #46's model.

## Extensibility Seam

The seam is the existing **environment-scoped, request-owned gateway resource
namespace**, not `proof` literals and not a new VPN policy abstraction. Keep the
environment interpolated and keep the gateway name prefix centralized in the
runtime Terraform module. A future AWS tenant works without policy edits; a
future gateway resource type must add an explicit ARN/action family and a
focused checker case instead of widening the current namespace.

For smoke behavior, the seam is `TERMINAL_STATUSES`. If the shared lifecycle
adds a terminal state, the canonical smoke fails promptly without another
command-local edit.

## Whole-Repository Surfaces In Scope

- global IAM boundary: `platform/terraform/global/iam/github-oidc.tf`;
- provisioner identity: `platform/terraform/modules/engine-provisioner/iam.tf`;
- AWS runtime range realization:
  `shifter/engine/provisioner/terraform/modules/range/vpn.tf`;
- existing IAM/ELB guardrails and tests:
  `scripts/check_tf_iam_elb_scope/`,
  `scripts/check_tf_iam_role_naming/`, `.pre-commit-config.yaml`,
  `.github/workflows/_quality.yml`, and the associated ADR registry/docs;
- smoke command and focused tests:
  `shifter/shifter_platform/cms/management/commands/run_post_deploy_smoke.py`
  and
  `shifter/shifter_platform/tests/mission_control/test_run_post_deploy_smoke_command.py`;
- canonical operator entrypoint: `scripts/smoke-test.sh` and
  `scripts/portal_deploy/portal_deploy.py`; and
- rollout surfaces: the separately applied `platform/terraform/global/iam`
  stack, then the normal `deploy.yml` proof dispatch, then the canonical Linux
  smoke and #1696 live UAT.

## Rollout Guardrail

`deploy.yml` does not apply `platform/terraform/global/iam`; bootstrap/manual
IAM owns that stack. Proof must receive the global boundary update before the
normal proof Portal apply installs the updated task-role policy. Applying only
`deploy.yml` leaves the old explicit deny live and reproduces the failure.

After the PR is integrated to `dev`, use the repository's existing global-IAM
apply path for `proof`, then dispatch the canonical Deploy workflow for
`aws-proof` from the integrated ref. The reusable post-deploy smoke job is
currently `inputs.is_dev`-gated, so proof verification uses the same canonical
`scripts/smoke-test.sh --variant linux` entrypoint manually with proof's trusted
environment/credentials; do not duplicate the smoke in a proof-only script.
The live #1696 Mission Control lease/extend/VPN/deadline walkthrough follows a
successful canonical range smoke.

## Gotchas And Anti-Patterns

- Do not add only the gateway role to the boundary carve-out and overlook the
  instance profile; Terraform would fail on the next IAM resource.
- Do not replace the boundary's explicit IAM deny with a broad allow, remove the
  Polaris controls, permit boundary mutation, or carve out `shifter-*`.
- Do not use `Resource = "*"`, remove request/resource tag conditions, or mix
  `gwy`, `net`, and `app` ARNs into one least-common-denominator statement.
- Do not authorize `CreateListener` against only the future listener ARN. AWS
  authorizes creation against the parent load balancer; require that parent's
  ownership resource tags and tag the listener in the create request so both
  sides of the ownership contract are effective.
- Do not accept a static checker that passes when the target policy/resource is
  absent, or a test that merely searches for action text without checking the
  boundary, ARN, conditions, and runtime tags.
- Do not add a second terminal-status list, use `ACTIVE_STATUSES` as its
  inverse, query Engine/ORM directly, or wait for timeout after a terminal CMS
  projection.
- Do not skip cleanup on terminal failure, and do not let cleanup failure hide
  the original terminal state.
- Do not broaden the automatic workflow to proof, change its advisory
  `continue-on-error` policy, or redesign smoke issue creation as part of this
  repair.

## Non-Goals And Implementation Boundaries

- No new gateway, shared VPN hub, protocol, target, route, certificate, profile,
  secret, persistence field, API, DTO, schema, or provider adapter.
- No changes to Mission Control/CTF authorization, profile delivery, leases,
  range status projection, compensation, or provider selection.
- No redesign of the CI boundary, Polaris role delegation, GWLB/NGFW behavior,
  managed-policy attachment topology, or global IAM deployment ownership.
- No new smoke workflow, proof-only script, retry framework, exception
  hierarchy, logging framework, or general polling abstraction.
- No deployment, merge, or live proof mutation during this architecture
  preflight; those remain downstream implementation and rollout work.
