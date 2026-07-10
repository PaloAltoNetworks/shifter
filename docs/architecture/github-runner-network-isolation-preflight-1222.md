# GitHub Runner Network Isolation Preflight (#1222)

Status: pre-implementation guidance

Date: 2026-06-28

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/1222>

This is a requirement-free preflight. The GitHub issue is the shipping
contract: self-hosted deploy runners must stop living in the account default
VPC, and range-created private-DNS VPC endpoints must no longer be able to
affect runner AWS API resolution. This note records architecture guardrails for
the implementation that follows; it does not move any runner.

## Scope Boundary

This is runner placement and DNS blast-radius work. It is not a CI routing
redesign, a range-network redesign, a portal application change, or a runner
autoscaling change.

The invariant to preserve is simple: the runner VPC DNS boundary must be a
network that range provisioning cannot deploy into. A range may keep creating
interface endpoints with `private_dns_enabled = true` in the range/default
workload network, but that private DNS must be scoped to a different VPC than
the runner.

## Architecture Decisions

- Keep the owning boundary in the existing runner Terraform root:
  `platform/terraform/global/github-runner/**`. It already has the placement
  seam: `var.vpc_id` and `var.subnet_id`. Do not create a parallel runner
  stack or change workflow labels to solve a network-placement issue.
- The selected runner network must be non-default and must be outside the range
  provisioning blast radius. Acceptable placements are a dedicated runner VPC or
  the portal VPC private tier. The account default VPC is explicitly invalid.
- Prefer private runner subnets with outbound egress through NAT or an approved
  proxy. GitHub traffic still needs internet egress; AWS API traffic can use
  VPC endpoints where the selected VPC owns them, but endpoints are not a
  substitute for GitHub egress.
- If the portal VPC is used, consume its existing outputs
  (`vpc_id`, `private_subnet_ids`) and endpoint/NAT posture. Do not rename the
  runner as a portal workload, do not open inbound rules from range CIDRs, and
  do not make portal application modules depend on runner lifecycle.
- If a dedicated runner VPC is used, keep it runner-specific. Reuse the portal
  VPC endpoint service list and tagging conventions where they fit, but do not
  copy portal public-workload, ALB, inspection, or application semantics into a
  fake portal VPC.
- The implementation should fail closed when configured with the default VPC.
  A comment in `*.tfvars` is not enough. Use Terraform data/precondition checks,
  a repo-native validation test, or an equivalent guard that blocks accidental
  default-VPC placement.
- Live VPC/subnet IDs are operational identifiers. ADR-004-R14 forbids
  committing them. Keep committed tfvars as placeholders and provide real
  account-local placement through a gitignored override or another approved
  deploy-time binding.
- Keep runner registration manual/operator-controlled as it is today. Moving
  the instance should not introduce GitHub PATs, registration tokens, or remove
  tokens into Terraform state, user data, SSM Parameter Store, workflow logs, or
  shell history.
- Do not weaken range private-DNS behavior to compensate for runner placement.
  Range SSM/STS/Bedrock endpoints with `private_dns_enabled = true` are valid
  inside the range VPC; the fix is to remove the runner from that DNS scope.

## Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #1222 |
| --- | --- | --- |
| Runner infrastructure | `platform/terraform/global/github-runner/{main.tf,variables.tf,outputs.tf,alarms.tf,README.md}` | Reuse the root and its `vpc_id` / `subnet_id` seam. Add only placement validation and docs needed for non-default networks. |
| Runner deploy wrapper | `scripts/runner-deploy.sh` | Preserve plan-by-default behavior and tracked lockfile handling. If live placement IDs need an override file, load it intentionally after the baseline instead of committing IDs. |
| Bootstrap guidance | `scripts/bootstrap/README.md`, `scripts/bootstrap/runner.py`, `docs/dev/deploy-secrets.md` | Keep the fresh-account order aligned: backend/OIDC first, runner root in a non-default network, then AWS deploy workflows. |
| Runner health | `platform/terraform/global/github-runner/alarms.tf`, `docs/ops/github-runner-health-alerts.md`, `docs/architecture/github-runner-health-alerting-preflight-292.md` | Network movement must keep alarms and manual registration runbooks coherent; do not collapse health monitoring into network placement. |
| Portal VPC option | `platform/terraform/modules/portal/vpc/{aws-endpoints.tf,outputs.tf}`, environment portal outputs | Use private subnet outputs and existing endpoint/NAT posture. Do not couple runner lifecycle to portal app modules. |
| Range private-DNS source | `platform/terraform/modules/range/vpc/ssm-endpoints.tf`, `docs/architecture/range-isolation-model.md` | Leave range endpoints scoped to range VPCs. The runner must not share that VPC. |
| Workflow trust boundary | ADR-003 in `docs/adr/index.yaml`, `scripts/adr_guard/adr_guard.py` deploy workflow checks | Do not route pull requests to self-hosted deploy runners or widen self-hosted runner exposure. |
| Terraform/security gates | `.tflint.hcl`, `platform/terraform/.checkov.yaml`, ADR-004, `scripts/adr_guard/adr_guard.py` | Terraform edits must pass the existing policy gates. New Checkov skips require ADR exception metadata. |
| Identifier hygiene | ADR-004-R14 in `docs/adr/index.yaml` | Never commit live VPC IDs, subnet IDs, runner instance IDs, account IDs, or state bucket names while wiring placement. |

## Cross-Cutting Layers

Security layers the intended design must pass:

- GitHub auth surface: runner registration tokens stay one-time manual
  artifacts. They must not appear in Terraform variables, user data, SSM
  command examples with real values, process argv captured in logs, or
  CloudWatch output.
- GitHub Actions trust surface: `runs-on: self-hosted` jobs remain trusted
  push/workflow_dispatch deploy paths. Pull-request validation must stay on
  hosted runners per ADR-003; this issue is not a reason to move more jobs into
  the deploy runner pool.
- AWS IAM surface: the runner EC2 role keeps the existing SSM agent, ECR, and
  CloudWatch metric permissions. A network move should not add broad
  `ec2:*`, `ssm:SendCommand`, `route53:*`, `secretsmanager:*`, or KMS grants.
  The range provisioner must not receive permission to create resources in a
  dedicated runner VPC.
- Secret and identifier surface: live network IDs are not secrets, but they are
  reconnaissance-sensitive and blocked by ADR-004-R14. Keep them in gitignored
  local/deploy overrides, Terraform state, or AWS APIs, not tracked files or
  design docs.
- Env-binding shape: placement remains Terraform input, not a Django setting,
  `shifter.yaml` setting, workflow boolean, or Cyberscript schema. If the
  implementation adds a safer override seam, it should be runner-root local and
  compatible with `scripts/runner-deploy.sh`.
- Terraform validation layer: selected `vpc_id` and `subnet_id` must be in the
  same VPC, the VPC must not be default, and the subnet must have an outbound
  path suitable for GitHub plus AWS APIs. Terraform type checks, TFLint,
  Checkov, and ADR guard remain the policy gates.
- OS/runtime exposure: the host still uses IMDSv2, SSM Session Manager, Docker,
  the Actions runner service, and the existing runner-health timer. Do not add
  DNS hacks in `/etc/hosts`, disable IMDSv2, expose SSH, or pass tokens through
  boot-time command arguments.
- DNS/network layer: private DNS for interface endpoints is VPC-scoped. The
  acceptance condition is satisfied only when range-created private-DNS records
  live in a different VPC DNS scope from the runner. NAT/proxy egress and VPC
  endpoints are availability mechanisms; they are not proof of isolation unless
  the runner is outside the range/default VPC.
- Error and log surface: validation failures should name the violated placement
  rule and docs path, not dump tfvars contents, Terraform state, registration
  tokens, environment variables, or SSM command payloads.
- Observability surface: keep using runner CloudWatch health alarms and VPC
  flow logs where enabled. A post-move check should prove DNS resolution for
  `ssm`, `sts`, and `ec2` resolves in the runner-owned network, not to range
  endpoints.

Maintainability incumbents the implementation must build on:

- `global/github-runner` is the runner owner.
- `portal/vpc` outputs are the portal placement contract if that option is
  chosen.
- `range/vpc` remains the range endpoint owner; do not patch it to work around
  runner placement.
- `scripts/runner-deploy.sh` is the local runner apply path.
- `scripts/bootstrap/README.md` and `docs/dev/deploy-secrets.md` are the
  fresh-account operator contract.
- ADR guard, TFLint, Checkov, and actionlint remain unchanged enforcement.

Extensibility seam:

Keep runner placement as an explicit runner-network contract. Today that is
`vpc_id` plus one `subnet_id`; the next obvious change is spreading runners
across multiple private subnets/AZs or switching between portal and dedicated
runner VPCs without rewriting resource logic. If that change is needed, evolve
the seam toward ordered `runner_subnet_ids` or a small runner-local placement
object. Do not encode `portal`, `dedicated`, or `default` as overloaded booleans
inside workflows or application config.

## Whole-Repo Scope

Likely in scope for implementation:

- `platform/terraform/global/github-runner/**`
- `scripts/runner-deploy.sh`
- `scripts/bootstrap/README.md` and possibly `scripts/bootstrap/runner.py`
- `docs/dev/deploy-secrets.md`
- `platform/terraform/environments/{dev,proof,prod}/portal/outputs.tf` when
  using portal placement outputs as operator input
- `docs/ops/github-runner-health-alerts.md` if replacement/re-registration
  steps change
- `changelog.d/1222.fixed.md` or `1222.changed.md` if the PR changes runtime
  deploy behavior

Usually out of scope:

- `.github/workflows/**` runner routing, unless validation or docs links need a
  narrow update.
- Range endpoint private-DNS behavior, scenario-pack content, and
  `settings.range_egress`.
- Portal application modules, Django settings, API schemas, controllers,
  services, repositories, exception hierarchies, or logging frameworks.
- GCP/GDC/Kubernetes networking.

## Gotchas And Anti-Patterns

- Do not keep a "temporary" runner in the default VPC after the new network is
  ready; one default-VPC runner preserves the failure mode.
- Do not treat a public subnet in a non-default VPC as equivalent to the target
  design. The accepted shape is private subnet egress through NAT/proxy unless
  a separate design explicitly accepts public placement.
- Do not rely on comments telling operators to avoid the default VPC. Make the
  Terraform or repo-native check fail closed.
- Do not commit live `vpc-*`, `subnet-*`, account IDs, or instance IDs while
  wiring the migration.
- Do not disable `private_dns_enabled` on range endpoints as the fix. That moves
  risk back into range functionality instead of isolating the runner.
- Do not add `/etc/hosts` overrides for AWS APIs on the runner. That hides the
  DNS-scope bug and will drift with regions/endpoints.
- Do not conflate portal VPC peering with shared DNS scope. VPC peering does not
  make the runner share the range VPC's private-DNS endpoint overrides.
- Do not grant range provisioners access to a dedicated runner VPC or place
  range runtime subnets in the portal/private runner subnet.
- Do not broaden runner security-group ingress. SSM Session Manager remains the
  access path; SSH/RDP from range or public CIDRs is not needed.
- Do not weaken ADR guard, TFLint, Checkov, actionlint, workflow exposure
  checks, or identifier hygiene to land the move.

## Non-Goals

- No implementation in this preflight note.
- No new autoscaling runner fleet, GitHub App, token broker, or runner
  registration automation.
- No CI scheduling/routing redesign.
- No range, scenario-pack, portal app, GCP, GDC, or Kubernetes implementation.
- No new shared schema, parser, DTO, service, repository, exception hierarchy,
  or logging framework.
- No Ground Control requirement or traceability object is created for this
  requirement-free issue.

## Validation Expectations

For this preflight documentation change, run:

```bash
python3 scripts/adr_guard/adr_guard.py --files docs/architecture/github-runner-network-isolation-preflight-1222.md --level fast
```

For the eventual implementation, run the repo-mandated checks for all touched
surfaces. At minimum, Terraform runner-root changes should pass:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```
