# Placeholder only. Do not commit live VPC/subnet IDs.
# The runner network must be non-default and outside range provisioning scope:
# use a dedicated runner VPC or the portal VPC private tier.
# See docs/dev/deploy-secrets.md ("Fresh AWS account bootstrap order", step 2).
#
# Alternatively (issue #1433) set create_runner_network = true to have Terraform
# provision a dedicated, ADR-004-R20-compliant runner VPC instead of supplying a
# live vpc_id/subnet_id; when set, the placeholders below are ignored. The
# bootstrap `runners` automation path enables this by default.
# create_runner_network = true
# runner_network_cidr   = "10.20.0.0/24"
vpc_id       = "vpc-xxxxxxxxxxxxxxxxx"    # dedicated runner VPC or portal VPC
subnet_id    = "subnet-xxxxxxxxxxxxxxxxx" # private subnet with outbound egress
runner_count = 3

github_org  = "Brad-Edwards"
github_repo = "shifter"

# Access via SSM Session Manager - no SSH required
