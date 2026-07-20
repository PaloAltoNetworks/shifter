# Portal SG Segmentation Preflight (#933)

Status: pre-implementation guidance

Date: 2026-06-20

Tracking issue: <https://github.com/Brad-Edwards/shifter/issues/933>

Primary AWS reference:
<https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html#security-group-referencing>

## Scope Boundary

This is a requirement-free architecture preflight. GitHub issue #933 is the
shipping contract: CTFd must not be able to open TCP connections directly to the
Django app on port 8000 or the Guacamole client/token API on port 8080. Only the
ALB and the already-intended portal service path may reach those targets.

Do not implement the Terraform change in this note. The implementation must fix
the segmentation regression without weakening the existing inspection route
assertion, ALB/WAF boundary, Guacamole token path, or repo guardrails.

## Architecture Decisions

- Treat reachability and inspection as separate controls. AWS Network Firewall
  can log and inspect routed traffic, but target security groups still own the
  L4 allow list for Django and Guacamole.
- The preferred posture is SG-scoped ingress where the live topology supports
  it: `portal/ec2` app ingress from the ALB SG, Guacamole client ingress from
  the ALB SG, and Guacamole token API ingress from the portal EC2 SG.
- Before claiming SG-only restores the path, root-cause the middlebox behavior
  against the live inspection topology. AWS documents that SG references do not
  allow traffic when routes forward traffic between subnets through a middlebox
  appliance; do not rely on SG references through the Network Firewall path
  unless the implementation proves the actual ALB-to-target flow still works.
- If CIDR ingress is genuinely required for inspected ALB traffic, CIDR scope
  must be an ALB-only subnet contract, not `module.vpc.public_subnet_cidrs`.
  CTFd, NAT, and future public workloads must not share any CIDR used as a
  target-service ingress source.
- The acceptance criterion is behavioral, not just structural: from the CTFd
  instance, TCP to portal:8000 and guacamole:8080 must fail closed, while ALB
  health checks and user traffic still reach the targets.

## Canonical Incumbents To Reuse

| Concern | Canonical incumbent | Guardrail for #933 |
| --- | --- | --- |
| Portal env roots | `platform/terraform/environments/{dev,prod}/portal/main.tf` | The broad `portal_app_from_alb_subnets` and `guacamole_client_from_alb_subnets` rules are the regression surface. Fix both environments consistently. |
| Django target SG | `platform/terraform/modules/portal/ec2/main.tf` | Reuse `aws_security_group_rule.app_from_alb`; do not add a parallel Django ingress module or application-level bypass. |
| Guacamole target SG | `platform/terraform/modules/guacamole/security.tf` | Reuse `guacamole_client_from_alb` and `guacamole_client_from_portal`; preserve the portal-to-token-API path but do not grant CTFd reachability. |
| Public edge | `platform/terraform/modules/portal/alb/main.tf` | Preserve HTTPS termination, WAF association, target group ownership, and the `/admin` fixed-response deny. Direct 8000/8080 access must not bypass these controls. |
| Portal VPC topology | `platform/terraform/modules/portal/vpc/{main,inspection,outputs}.tf` | Any subnet split belongs at the VPC boundary with typed outputs, not inside app modules. Keep route-table ownership centralized here. |
| CTFd placement | `platform/terraform/modules/portal/ctfd/` and the env-root `module "ctfd"` block | If CIDR ingress stays, move CTFd to a separate public-workload subnet tier or equivalent placement that is not in the ALB ingress CIDR set. |
| Inspection assertion | `scripts/assert_portal_inspection/` and `portal_inspection_assertion` outputs | Keep route/endpoint proof intact. If adding reachability proof, extend this tested assertion surface or add a sibling helper with the same CLI/test style. |
| SG CIDR guardrail | `scripts/check_tf_sg_cidrs/`, `.pre-commit-config.yaml`, `.github/workflows/_quality.yml` | The existing checker is range-scoped and allows `var.portal_vpc_cidr`; do not assume it protects portal target SGs. A portal-specific guard must be tested and wired in both local and CI surfaces. |
| Architecture and IaC gates | `scripts/adr_guard/adr_guard.py`, `docs/adr/index.yaml`, `docs/adr/exceptions.yaml`, `.tflint.hcl`, `platform/terraform/.checkov.yaml` | Guardrail-file or exception changes must update ADR docs in the same change. Checkov/TFLint/ADR guard remain blocking. |

## Cross-Cutting Layers The Design Must Pass

- Public auth and edge policy: requests must enter through ALB 80/443, WAF, and
  the ALB `/admin` deny. The design satisfies this only if target SGs do not
  admit CTFd or other public-subnet workloads directly on 8000/8080.
- Network reachability policy: Django and Guacamole target SGs must allow only
  intended source identities. Use SG references where proven viable; otherwise
  use an ALB-only subnet CIDR output. Do not use the whole public tier as an
  identity proxy.
- Inspection route policy: `enable_portal_inspection` and the existing
  `portal_inspection_assertion` prove route and endpoint wiring only. They do
  not prove segmentation from CTFd and must not be treated as a substitute for
  target SG restrictions.
- Terraform shape validation: new subnet tiers, CIDR outputs, feature toggles,
  or reachability assertion inputs must be typed in `variables.tf`/`outputs.tf`
  and validated at plan time where possible. Environment-specific values stay
  in tfvars or gitignored `local.auto.tfvars`.
- Secret-handling surface: this fix should require no new secret. If live
  reachability is automated through SSM, commands may use instance IDs, DNS
  names, ports, and timeout values only. Do not print Secrets Manager values,
  Guacamole JSON auth secrets, Django secrets, RDP passwords, SSH keys, or
  rendered tfvars.
- OS/process exposure: do not put tokens or credentials in shell argv, user
  data, Docker env, or cloud-init logs while testing connectivity. Bounded
  `nc`/`timeout` style probes from CTFd are acceptable because they carry no
  credential.
- Error envelope and observability: failures belong in Terraform validation,
  post-apply assertion output, GitHub Actions `::error::` diagnostics, VPC Flow
  Logs, and Network Firewall FLOW/ALERT logs. Do not add Django exception
  classes, API DTOs, or user-facing error envelopes for infrastructure
  segmentation.

## Extensibility Seam

The durable seam is subnet purpose, exposed from the portal VPC module:

- ALB ingress subnets and CIDRs for ALB-only source-CIDR fallback.
- Public workload subnets for CTFd and any future public EC2 workload.
- Private service subnets for Django, Guacamole, Redis, RDS, and the engine
  provisioner.

If CIDR-based ingress remains necessary, target modules should consume the
ALB-only CIDR output, not a hand-built list in each env root. A future public
service can then join the public-workload tier without re-editing Django or
Guacamole ingress. Do not overload `enable_portal_inspection` to mean
"permission to widen target security groups."

## Gotchas And Anti-Patterns

- Do not assume SG references survive a routed middlebox path. AWS documents a
  limitation for security-group references when traffic is routed through a
  middlebox; prove the exact Network Firewall behavior before removing a CIDR
  fallback.
- Do not keep `module.vpc.public_subnet_cidrs` as a target ingress source while
  CTFd can run in those subnets. CTFd has broad egress, so the target SG is the
  failing or passing control.
- Do not hardcode ALB ENI private IPs. ALB nodes and ENIs are elastic; subnet
  purpose or SG references are the maintainable identities.
- Do not add a "deny CTFd" SG rule. AWS security groups are allow-only; the fix
  is to remove CTFd from all matching allow sources.
- Do not treat WAF or the `/admin` ALB rule as protecting direct 8000/8080
  traffic. They only apply when traffic actually reaches the ALB listener.
- Do not weaken or bypass `scripts/assert_portal_inspection`; this issue fixes
  segmentation on top of the inspection path, not instead of it.
- Do not broaden `scripts/check_tf_sg_cidrs` casually. Its current
  `var.portal_vpc_cidr` allowance is for range-side portal-to-range access and
  is not a portal target-service policy.
- Do not move CTFd into private service subnets just to satisfy the test unless
  its public HTTP/HTTPS contract is also redesigned. Public CTFd still needs a
  deliberate public-workload placement.

## Non-Goals

- No Django, CTF, Guacamole application code, migrations, DTOs, controllers,
  repositories, exception hierarchy, or API error-envelope work.
- No WAF rule rewrite, Cognito/OIDC change, ALB listener redesign, or Guacamole
  token protocol change.
- No range VPC redesign, GCP/Kubernetes/Helm change, or Network Firewall
  enforcement-mode flip.
- No new secret store, KMS grant pattern, logging pipeline, workflow engine, or
  deployment-secret mechanism.
- No implementation plan in this preflight note.

## Validation Expectations

The implementation should prove both structure and behavior. At minimum for
portal Terraform or guardrail changes:

```bash
python3 scripts/adr_guard/adr_guard.py --all --level ci
TFLINT_CONFIG="$(pwd)/.tflint.hcl"; cd platform/terraform && tflint --recursive --config "$TFLINT_CONFIG"
```

Also run Terraform fmt/validate for the touched portal roots/modules, Checkov
through the repo-standard path, and `actionlint` if workflow files change. If a
checker or assertion helper is changed, run its unit tests and add a regression
fixture where CTFd is in the allowed source CIDR and therefore fails the check.
