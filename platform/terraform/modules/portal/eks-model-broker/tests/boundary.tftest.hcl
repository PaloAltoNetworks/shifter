mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/test-invoke" }
  }
  mock_resource "aws_lb" {
    defaults = {
      arn      = "arn:aws:elasticloadbalancing:us-east-2:123456789012:loadbalancer/net/test/0123456789abcdef"
      dns_name = "internal-models.us-east-2.elb.amazonaws.com"
      zone_id  = "Z123456"
    }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/test/0123456789abcdef" }
  }
  mock_resource "aws_vpc_endpoint" {
    defaults = { network_interface_ids = ["eni-1234567890abcdef0"] }
  }
  mock_data "aws_network_interface" {
    defaults = { private_ip = "10.42.0.10" }
  }
}

override_resource {
  target = aws_iam_role.broker
  values = { arn = "arn:aws:iam::123456789012:role/test-broker" }
}

variables {
  settings = {
    enabled                 = true
    hostname                = "models.example.test"
    admitted_subnets        = ["10.50.1.0/24"]
    tls_secret_name         = "broker-tls"
    control_tls_secret_name = "control-tls"
    trust_configmap_name    = "model-ca"
    invocation_models       = { primary = "anthropic.example-model-v1:0" }
  }
  cluster_name             = "shifter-test"
  region                   = "us-east-2"
  permissions_boundary_arn = "arn:aws:iam::123456789012:policy/shifter-test-ci-role-boundary"
  oidc_provider_arn        = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-2.amazonaws.com/id/EXAMPLE"
  oidc_issuer              = "https://oidc.eks.us-east-2.amazonaws.com/id/EXAMPLE"
  provisioner_subject      = "arn:aws:iam::123456789012:role/test-provisioner"
  vpc_id                   = "vpc-mock-platform"
  vpc_cidr                 = "10.42.0.0/16"
  private_subnets          = { "us-east-2a" = { id = "subnet-mock-platform", cidr = "10.42.0.0/20" } }
  range_vpc_id             = "vpc-mock-range"
  range_vpc_cidr           = "10.50.0.0/16"
}

run "private_broker_boundary" {
  command = apply
  assert {
    condition = (
      aws_lb.broker.internal && aws_lb.broker.enable_deletion_protection && aws_lb.broker.load_balancer_type == "network" &&
      aws_lb_listener.broker.protocol == "TCP" && aws_lb_listener.broker.port == 443 &&
      aws_lb_target_group.broker.preserve_client_ip && !aws_lb_target_group.broker.proxy_protocol_v2 &&
      aws_lb_target_group.broker.health_check[0].path == "/health/ready" &&
      aws_lb_target_group.broker.target_type == "ip"
    )
    error_message = "Guest authorization requires private TLS passthrough and preserved socket peers."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role.broker.assume_role_policy).Statement[0].Condition.StringEquals["oidc.eks.us-east-2.amazonaws.com/id/EXAMPLE:sub"] == "system:serviceaccount:shifter-platform:model-broker" &&
      jsondecode(aws_iam_role_policy.broker.policy).Statement[0].Action == ["sts:AssumeRole"] &&
      jsondecode(aws_iam_role_policy.broker.policy).Statement[0].Resource == [aws_iam_role.invocation["primary"].arn] &&
      aws_iam_role.broker.permissions_boundary == var.permissions_boundary_arn
    )
    error_message = "Broker identity must receive only exact invocation-role assumption, never platform secret access."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role.invocation["primary"].assume_role_policy).Statement[0].Principal.AWS == aws_iam_role.broker.arn &&
      jsondecode(aws_iam_role_policy.invocation["primary"].policy).Statement[0].Resource == ["arn:aws:bedrock:us-east-2::foundation-model/anthropic.example-model-v1:0"] &&
      toset(jsondecode(aws_iam_role_policy.invocation["primary"].policy).Statement[0].Action) == toset(["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:CountTokens"]) &&
      aws_iam_role.invocation["primary"].permissions_boundary == var.permissions_boundary_arn
    )
    error_message = "Invocation authority must bind the broker, region, model, and bounded native API surface."
  }
  assert {
    condition = (
      toset(keys(aws_vpc_endpoint.provider)) == toset(["sts", "bedrock-runtime"]) &&
      alltrue([for endpoint in aws_vpc_endpoint.provider : endpoint.private_dns_enabled]) &&
      output.deployment.endpoint_cidrs == tolist(["10.42.0.10/32", "10.42.0.10/32"]) &&
      aws_vpc_security_group_ingress_rule.listener["10.50.1.0/24"].from_port == 443 &&
      length(aws_route53_zone.broker.vpc) == 2 &&
      output.deployment.guest_endpoint_cidrs == tolist(["10.42.0.10/32"])
    )
    error_message = "Broker network must use exact private API endpoints and range-private DNS/routing."
  }
}

run "reject_foreign_guest_subnet" {
  command = plan
  variables {
    settings = {
      enabled                 = true
      hostname                = "models.example.test"
      admitted_subnets        = ["10.99.0.0/24"]
      tls_secret_name         = "broker-tls"
      control_tls_secret_name = "control-tls"
      trust_configmap_name    = "model-ca"
      invocation_models       = { primary = "anthropic.example-model-v1:0" }
    }
  }
  expect_failures = [terraform_data.boundary]
}

run "reject_overlapping_vpcs" {
  command = plan
  variables { range_vpc_cidr = "10.42.0.0/16" }
  expect_failures = [terraform_data.boundary]
}
