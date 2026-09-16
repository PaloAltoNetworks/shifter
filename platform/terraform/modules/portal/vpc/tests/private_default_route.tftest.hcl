# Portal VPC private-default-route contract test (#1134).
#
# Proves the ordering-safe invariant for the private-tier IPv4 default route:
# ONE aws_route.private_default resource owns (route_table_id, 0.0.0.0/0) per AZ,
# and its target is selected by enable_portal_inspection. Before #1134 two
# independent resources (aws_route.private_nat and
# aws_route.private_default_via_firewall) each claimed that destination, so an
# enable_portal_inspection toggle create/destroyed two resources for one AWS
# object and failed closed with RouteAlreadyExists. With one owner a toggle is an
# in-place ReplaceRoute (target change), never a create-before-delete race.
#
# Credential-free: mock_provider synthesizes AWS data/resources; the firewall
# endpoint ids (normally read live from firewall_status.sync_states) are supplied
# via mock_resource defaults so the inspection-on wiring plans. Run with:
#   terraform -chdir=platform/terraform/modules/portal/vpc test

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-2a", "us-east-2b", "us-east-2c"]
    }
  }

  # Valid-shaped ARNs for the Network Firewall objects: the inspection-on run uses
  # command = apply so the firewall endpoint map materializes, and the AWS
  # provider ARN-validates these references at apply (a random mock string is
  # rejected as "invalid prefix").
  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-2:123456789012:key/00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "aws_networkfirewall_rule_group" {
    defaults = {
      arn = "arn:aws:network-firewall:us-east-2:123456789012:stateful-rulegroup/mock-portal-anomalies"
    }
  }

  mock_resource "aws_networkfirewall_firewall_policy" {
    defaults = {
      arn = "arn:aws:network-firewall:us-east-2:123456789012:firewall-policy/mock-portal-policy"
    }
  }

  mock_resource "aws_networkfirewall_firewall" {
    defaults = {
      arn = "arn:aws:network-firewall:us-east-2:123456789012:firewall/mock-portal-firewall"
      firewall_status = [{
        sync_states = [
          {
            availability_zone = "us-east-2a"
            attachment        = [{ endpoint_id = "vpce-fwmock0a000000000" }]
          },
          {
            availability_zone = "us-east-2b"
            attachment        = [{ endpoint_id = "vpce-fwmock0b000000000" }]
          },
        ]
      }]
    }
  }
}

variables {
  name_prefix                 = "test-portal"
  vpc_cidr                    = "10.0.0.0/16"
  az_count                    = 2
  enable_nat_gateway          = true
  tags                        = { Environment = "test" }
  enable_flow_logs            = false
  log_retention_days          = 7
  firewall_log_retention_days = 7
  permissions_boundary_arn    = "arn:aws:iam::123456789012:policy/test-boundary"
}

# Inspection OFF: one default route per AZ, target is NAT (vpc_endpoint_id null).
run "inspection_off_single_owner_via_nat" {
  command = plan

  variables {
    enable_portal_inspection = false
    enable_log_aggregation   = false
  }

  assert {
    condition     = length(aws_route.private_default) == 2
    error_message = "there must be exactly one private_default route per AZ when NAT is enabled"
  }

  assert {
    condition     = aws_route.private_default[0].vpc_endpoint_id == null
    error_message = "inspection-off private default must target NAT, not a firewall endpoint"
  }
}

# Inspection ON: same single owner per AZ, target is the firewall endpoint
# (nat_gateway_id null). Count is unchanged by the toggle => an inspection flip
# is an in-place target change on the same resource, not a create/destroy.
#
# Uses command = apply (still credential-free under mock_provider) so the mocked
# firewall_status.sync_states materializes and the per-AZ endpoint map resolves;
# the vpc_endpoint_id values are unknown-after-apply under command = plan.
run "inspection_on_single_owner_via_firewall" {
  command = apply

  variables {
    enable_portal_inspection = true
    enable_log_aggregation   = true
  }

  assert {
    condition     = length(aws_route.private_default) == 2
    error_message = "the private_default count must be controlled only by enable_nat_gateway, unchanged by the inspection toggle"
  }

  assert {
    condition     = aws_route.private_default[0].nat_gateway_id == null
    error_message = "inspection-on private default must target the firewall endpoint, not NAT directly"
  }

  # Assert the POSITIVE, not just the absence of NAT: each AZ's private default
  # must resolve to that SAME AZ's firewall endpoint. A broken az-index mapping,
  # a stale value, or a failed lookup() would silently blackhole or cross-wire
  # private egress (exactly the #1134 hazard) while nat_gateway_id == null still
  # held. Pin to the mock endpoint ids keyed by availability zone.
  assert {
    condition     = aws_route.private_default[0].vpc_endpoint_id == "vpce-fwmock0a000000000"
    error_message = "inspection-on private default for us-east-2a must target that AZ's firewall endpoint (vpce-fwmock0a000000000)"
  }

  assert {
    condition     = aws_route.private_default[1].vpc_endpoint_id == "vpce-fwmock0b000000000"
    error_message = "inspection-on private default for us-east-2b must target that AZ's firewall endpoint (vpce-fwmock0b000000000)"
  }
}

# NAT disabled: no private default route at all.
run "no_nat_no_default_route" {
  command = plan

  variables {
    enable_nat_gateway       = false
    enable_portal_inspection = false
    enable_log_aggregation   = false
  }

  assert {
    condition     = length(aws_route.private_default) == 0
    error_message = "private_default must not exist when NAT is disabled"
  }
}
