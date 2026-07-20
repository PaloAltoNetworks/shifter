Allow the range provisioner to create the per-range POLARIS agent IAM role
under the CI permissions boundary. The polaris agent feature (#1377) creates a
per-range agent role at provision time, but the provisioner's anti-escalation
boundary (#253) denied all `iam:CreateRole`, so a polaris range could never
reach `terraform apply`. The boundary now carves the
`shifter-<env>-*-polaris-agent` role namespace out of the IAM deny. This is
safe because the provisioner identity policy already permits `iam:CreateRole`
there only with this same boundary attached (`iam:PermissionsBoundary`
condition) and grants no boundary-strip action, so every created agent role
stays capped by the boundary (the AWS permissions-boundary delegation pattern).
A new `DenyPolarisAgentBoundaryTamper` statement re-denies boundary removal on
that namespace as defense-in-depth.
