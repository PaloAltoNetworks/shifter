# Range VPC firewall contract test (#1134).
#
# Proves the ordering-safe invariant for the range Network Firewall IP
# allowlist: the victim-IP stateful rule group is ONE stable resource whose
# cardinality never tracks the CIDR-chunk count. Before #1134 the group used
# `count = length(local.cidr_chunks)`, so shrinking the allowlist destroyed
# rule groups the firewall policy still referenced and `apply` failed closed
# with InvalidOperationException. Consolidating to a single group (chunks become
# internal ALLOWED_IPS_<n> variables/rules) makes a shrink an in-place content
# update instead of a rule-group destroy.
#
# Credential-free: mock_provider synthesizes all AWS data/resources. The
# firewall endpoint id (normally read from live firewall_status.sync_states) is
# supplied via mock_resource defaults so the private->firewall route plans.
# Run with:
#   terraform -chdir=platform/terraform/modules/range/vpc test

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-2a", "us-east-2b", "us-east-2c"]
    }
  }

  mock_resource "aws_networkfirewall_firewall" {
    defaults = {
      firewall_status = [{
        sync_states = [{
          availability_zone = "us-east-2a"
          attachment = [{
            endpoint_id = "vpce-firewallmock0000000"
          }]
        }]
      }]
    }
  }
}

variables {
  name_prefix              = "test-range"
  vpc_cidr                 = "10.1.0.0/16"
  portal_vpc_cidr          = "10.0.0.0/16"
  tags                     = { Environment = "test" }
  agent_s3_bucket          = "test-agent-bucket"
  environment              = "test"
  permissions_boundary_arn = "arn:aws:iam::123456789012:policy/test-boundary"
  enable_network_firewall  = true
}

# Empty allowlist: the group still exists (one stable resource) with an inert
# alert-only placeholder rule; it is never absent just because there are no
# CIDRs. This is the default posture for most tenants.
run "empty_allowlist_keeps_single_group" {
  command = plan

  variables {
    victim_allowed_cidrs = []
  }

  assert {
    condition     = length(aws_networkfirewall_rule_group.victim_ips) == 1
    error_message = "victim_ips must be exactly one rule group even when the allowlist is empty"
  }

  assert {
    condition     = strcontains(aws_networkfirewall_rule_group.victim_ips[0].rule_group[0].rules_source[0].rules_string, "allowlist empty")
    error_message = "empty allowlist must render the inert alert-only placeholder rule, not a pass rule"
  }
}

# One chunk (<=300 CIDRs): still exactly one group.
run "one_chunk_single_group" {
  command = plan

  variables {
    victim_allowed_cidrs = ["203.0.113.0/24", "198.51.100.0/24"]
  }

  assert {
    condition     = length(aws_networkfirewall_rule_group.victim_ips) == 1
    error_message = "victim_ips must be exactly one rule group for a single-chunk allowlist"
  }

  assert {
    condition     = strcontains(aws_networkfirewall_rule_group.victim_ips[0].rule_group[0].rules_source[0].rules_string, "ALLOWED_IPS_1")
    error_message = "a non-empty allowlist must render per-chunk ALLOWED_IPS_<n> pass rules"
  }
}

# More than 300 CIDRs => multiple internal chunks, but STILL one rule group.
# This is the regression the issue is about: cardinality must not track chunks.
run "many_chunks_still_single_group" {
  command = plan

  variables {
    # 301 unique canonical /24s => 2 chunks of the 300-CIDR chunk size.
    victim_allowed_cidrs = [for i in range(301) : cidrsubnet("10.128.0.0/9", 15, i)]
  }

  assert {
    condition     = length(aws_networkfirewall_rule_group.victim_ips) == 1
    error_message = "victim_ips must remain a single rule group regardless of how many CIDR chunks the allowlist spans"
  }

  assert {
    condition     = strcontains(aws_networkfirewall_rule_group.victim_ips[0].rule_group[0].rules_source[0].rules_string, "ALLOWED_IPS_2")
    error_message = "a two-chunk allowlist must render ALLOWED_IPS_2 inside the single group"
  }
}
