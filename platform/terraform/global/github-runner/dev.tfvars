# Runner network placement (ADR-004-R20).
#
# aws-dev opts into the account default VPC via the documented escape hatch:
# with allow_default_vpc = true and vpc_id/subnet_id left empty, the stack
# auto-resolves the default VPC and one of its subnets, so no live VPC/subnet
# IDs are committed (ADR-004-R14). This accepts the range private-DNS collision
# risk for dev; the design is being reassessed (see the issue in ADR-004-R20).
#
# To use an isolated network instead, set allow_default_vpc = false and supply a
# non-default vpc_id/subnet_id (a dedicated runner VPC or the portal VPC private
# tier) via a gitignored override, never committed here.
allow_default_vpc = true

runner_count = 3

github_org  = "Brad-Edwards"
github_repo = "shifter"

# Access via SSM Session Manager - no SSH required
