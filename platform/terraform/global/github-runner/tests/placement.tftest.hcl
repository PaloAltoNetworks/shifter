# Runner network placement contract test (ADR-004-R20, issue #1437).
#
# Proves how the runner root selects its network across the three supported
# inputs, and that default-subnet discovery runs only for the default-VPC
# exception. A managed network with a retained allow_default_vpc opt-in on an
# account with no default VPC must not run discovery: before #1437 it did, and
# one([]) fed a null into the subnet filter ("Null value found in list"), so a
# fresh account failed on a lookup the managed path never uses. Teardown
# (scripts/bootstrap/aws_env_destroy.py) also reads discovery's presence in
# state as evidence that the default-VPC exception was applied.
#
# Credential-free: mock_provider synthesizes AWS data/resources, and
# override_data pins the default-VPC and subnet lookups per run. Run with:
#   terraform -chdir=platform/terraform/global/github-runner init -backend=false
#   terraform -chdir=platform/terraform/global/github-runner test

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-2a"] }
  }
  mock_data "aws_region" {
    defaults = { name = "us-east-2", region = "us-east-2" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-2:123456789012:key/00000000-0000-0000-0000-000000000000" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-2:123456789012:log-group:mock" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-east-2:123456789012:mock" }
  }
}

variables {
  runner_count = 1
}

# Managed network with a retained opt-in, on an account with no default VPC:
# discovery must not run.
run "managed_skips_default_discovery" {
  command = plan

  variables {
    create_runner_network = true
    allow_default_vpc     = true
  }

  override_data {
    target = data.aws_vpcs.default
    values = { ids = [] }
  }

  assert {
    condition     = length(data.aws_subnets.default) == 0
    error_message = "default-subnet discovery must not run when a managed network is created"
  }
}

run "default_opt_in_discovers" {
  command = plan

  variables {
    allow_default_vpc = true
  }

  override_data {
    target = data.aws_vpcs.default
    values = { ids = ["vpc-0default000000000"] }
  }
  override_data {
    target = data.aws_subnets.default
    values = { ids = ["subnet-0default00000000"] }
  }
  override_data {
    target = data.aws_subnet.runner
    values = { vpc_id = "vpc-0default000000000" }
  }

  assert {
    condition     = length(data.aws_subnets.default) == 1
    error_message = "default opt-in without an explicit subnet must discover a default subnet"
  }
  assert {
    condition     = aws_security_group.runner.vpc_id == "vpc-0default000000000" && aws_instance.runner[0].subnet_id == "subnet-0default00000000"
    error_message = "default opt-in must place the runner in the default VPC and its discovered subnet"
  }
}

# Default-VPC exception with an explicit subnet: the subnet_id == "" clause alone
# must suppress discovery. This is also the shape teardown must recognize from
# the recorded default VPC IDs rather than the discovery marker.
run "default_opt_in_with_explicit_subnet_skips_discovery" {
  command = plan

  variables {
    allow_default_vpc = true
    subnet_id         = "subnet-0explicitdefault"
  }

  override_data {
    target = data.aws_vpcs.default
    values = { ids = ["vpc-0default000000000"] }
  }
  override_data {
    target = data.aws_subnet.runner
    values = { vpc_id = "vpc-0default000000000" }
  }

  assert {
    condition     = length(data.aws_subnets.default) == 0
    error_message = "an explicit subnet_id must suppress default-subnet discovery even under the default-VPC opt-in"
  }
  assert {
    condition     = aws_security_group.runner.vpc_id == "vpc-0default000000000" && aws_instance.runner[0].subnet_id == "subnet-0explicitdefault"
    error_message = "the default-VPC opt-in with an explicit subnet must use the default VPC and that subnet"
  }
}

run "explicit_network_used_without_discovery" {
  command = plan

  variables {
    vpc_id    = "vpc-0external00000000"
    subnet_id = "subnet-0external0000000"
  }

  override_data {
    target = data.aws_vpcs.default
    values = { ids = ["vpc-0default000000000"] }
  }
  override_data {
    target = data.aws_subnet.runner
    values = { vpc_id = "vpc-0external00000000" }
  }

  assert {
    condition     = length(data.aws_subnets.default) == 0
    error_message = "an explicit network must not discover a default subnet"
  }
  assert {
    condition     = aws_security_group.runner.vpc_id == "vpc-0external00000000" && aws_instance.runner[0].subnet_id == "subnet-0external0000000"
    error_message = "an explicit network must place the runner in the supplied VPC and subnet"
  }
}

# A created runner network wins over an explicit vpc_id/subnet_id.
run "managed_network_wins_over_explicit" {
  command = plan

  variables {
    create_runner_network = true
    vpc_id                = "vpc-0external00000000"
    subnet_id             = "subnet-0external0000000"
  }

  override_module {
    target = module.runner_network[0]
    outputs = {
      vpc_id           = "vpc-0managed000000000"
      runner_subnet_id = "subnet-0managed00000000"
    }
  }
  override_data {
    target = data.aws_vpcs.default
    values = { ids = [] }
  }
  override_data {
    target = data.aws_subnet.runner
    values = { vpc_id = "vpc-0managed000000000" }
  }

  assert {
    condition     = aws_security_group.runner.vpc_id == "vpc-0managed000000000" && aws_instance.runner[0].subnet_id == "subnet-0managed00000000"
    error_message = "a created runner network must take precedence over an explicit vpc_id/subnet_id"
  }
}

run "default_vpc_rejected_without_opt_in" {
  command = plan

  variables {
    vpc_id    = "vpc-0default000000000"
    subnet_id = "subnet-0default00000000"
  }

  override_data {
    target = data.aws_vpcs.default
    values = { ids = ["vpc-0default000000000"] }
  }
  override_data {
    target = data.aws_subnet.runner
    values = { vpc_id = "vpc-0default000000000" }
  }

  expect_failures = [aws_security_group.runner]
}
