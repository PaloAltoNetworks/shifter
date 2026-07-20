# Module contract test for the portal VPC module (issue #1528, tracked #1597).
#
# Proves the `az_count` structural invariant documented in variables.tf: the
# module carves three /20 subnet tiers (public, private, public-workload) from
# vpc_cidr via cidrsubnet(vpc_cidr, 4, N), and reserves the inspection-firewall
# /28 tier inside /20 block 15. az_count must stay in [1, 5] so the three /20
# bands occupy blocks 0-14 and never collide with each other or block 15. If
# that bound is ever loosened without redoing the index math, this test fails.
#
# Credential-free: mock_provider synthesizes all AWS data/resources, and the
# variable-validation failures abort the plan before any data source is read,
# so the test needs no AWS account. Run with:
#   terraform -chdir=platform/terraform/modules/portal/vpc test

mock_provider "aws" {}

variables {
  name_prefix                 = "test-portal"
  vpc_cidr                    = "10.0.0.0/16"
  az_count                    = 2
  enable_nat_gateway          = false
  tags                        = { Environment = "test" }
  enable_flow_logs            = false
  log_retention_days          = 7
  enable_portal_inspection    = false
  enable_log_aggregation      = false
  firewall_log_retention_days = 7
  permissions_boundary_arn    = "arn:aws:iam::123456789012:policy/test-boundary"
}

run "rejects_az_count_above_five" {
  command = plan

  variables {
    az_count = 6
  }

  expect_failures = [var.az_count]
}

run "rejects_az_count_below_one" {
  command = plan

  variables {
    az_count = 0
  }

  expect_failures = [var.az_count]
}
