# Runner network placement (ADR-004-R20, issue #1437).
#
# Standard: a dedicated, non-default runner VPC provisioned by
# modules/github-runner-network (private runner subnet, NAT-only egress, no
# private-DNS interface endpoints, encrypted flow logs). It needs no portal or
# range dependency, so it works on a fresh account, and no live VPC/subnet IDs
# are committed (ADR-004-R14).
#
# To place the runner in an existing compliant network instead (for example the
# portal VPC private tier), supply vpc_id / subnet_id via a gitignored
# local.auto.tfvars (never committed here) and run
# `deploy.py runners --use-existing-network`, which passes
# -var=create_runner_network=false after this file. Setting it false in
# local.auto.tfvars alone does not work: -var-file values override *.auto.tfvars.
#
# allow_default_vpc (default false) is a narrow, documented exception, not a
# supported placement for this environment: a range's private-DNS VPC endpoints
# can hijack a default-VPC runner's AWS API resolution.
create_runner_network = true

runner_count = 3

github_org  = "Brad-Edwards"
github_repo = "shifter"

# Access via SSM Session Manager - no SSH required
