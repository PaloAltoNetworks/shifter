# Placeholder only. Do not commit live VPC/subnet IDs.
# The runner network must be non-default and outside range provisioning scope:
# use a dedicated runner VPC or the portal VPC private tier.
# See docs/dev/deploy-secrets.md ("Fresh AWS account bootstrap order", step 2).
vpc_id       = "vpc-xxxxxxxxxxxxxxxxx"    # dedicated runner VPC or portal VPC
subnet_id    = "subnet-xxxxxxxxxxxxxxxxx" # private subnet with outbound egress
runner_count = 3

github_org  = "Brad-Edwards"
github_repo = "shifter"

# Access via SSM Session Manager - no SSH required
