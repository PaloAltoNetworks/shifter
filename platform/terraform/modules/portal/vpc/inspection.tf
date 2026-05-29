# Portal east-west inspection boundary (#122).
#
# Inserts an AWS Network Firewall between the portal public tier (ALB) and
# the private services tier (Django EC2, RDS, Redis, Guacamole ECS) so
# internal traffic between the two is route-backed, logged, and inspectable.
#
# v1 scope:
#   - Per-AZ firewall subnets, per-AZ Network Firewall endpoints, and
#     per-AZ public/private/firewall route tables, so the firewall is
#     not a single zonal failure dependency on the portal ingress path.
#   - Complete public<->private route matrix: every public RT routes
#     every private subnet CIDR through its same-AZ firewall endpoint
#     (and the symmetric private->public matrix), so cross-AZ flows
#     created by ALB cross-zone load balancing and by the single shared
#     NAT do not fall back to implicit local routing and bypass
#     inspection.
#   - Stateful default = pass; a baseline rule group ALERTs on protocols
#     that have no legitimate east-west use in the portal (SSH/RDP/ICMP).
#   - FLOW + ALERT logs go to a CMK-encrypted CloudWatch log group; the env
#     root subscribes that log group through the existing log-aggregation
#     pipeline.
#
# Stateful symmetry trade-off:
#   ALB cross-zone load balancing is always on for ALB (the platform
#   cannot turn it off), and the portal runs a single shared NAT. So
#   public<->private and private<->Internet flows can legitimately cross
#   AZs in either direction. With per-AZ firewall endpoints, cross-AZ
#   flows are inspected by different endpoints on the forward and return
#   legs (asymmetric stateful). This is compatible with the visibility-
#   first v1 policy (pass + alert + FLOW) because rules fire per packet
#   on whichever endpoint observes it and FLOW logs from both endpoints
#   reconstruct the flow. A stateful drop-by-default posture would
#   require a centralized inspection topology (single endpoint via
#   Transit Gateway, GWLB with consistent hashing, or single-AZ portal
#   appliance) — all deferred beyond this issue.
#
# Out of scope (explicit deferrals):
#   - Stateful-symmetric inspection for cross-AZ flows (see trade-off
#     above).
#   - Inspection of portal<->range peering traffic.

locals {
  # Default firewall subnets to /28 blocks at the top of the VPC /16 so
  # they do not collide with the public/private /20 tiers at the bottom.
  # firewall_subnet_cidr (singular) on var is the v0 single-AZ override;
  # the per-AZ default below is preferred. If both are set, the per-AZ
  # default still wins for indexes > 0 (the override only covers index 0
  # for backwards-compat).
  firewall_subnet_cidrs = [
    for i in range(var.az_count) :
    var.firewall_subnet_cidr != "" && i == 0
    ? var.firewall_subnet_cidr
    : cidrsubnet(var.vpc_cidr, 12, 4080 + i)
  ]
}

# ------------------------------------------------------------------------------
# Per-AZ firewall subnets + route tables
# ------------------------------------------------------------------------------

resource "aws_subnet" "firewall" {
  count = var.enable_portal_inspection ? var.az_count : 0

  vpc_id                  = aws_vpc.this.id
  cidr_block              = local.firewall_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-subnet-${local.azs[count.index]}"
    Tier = "firewall"
  })
}

resource "aws_route_table" "firewall" {
  count = var.enable_portal_inspection ? var.az_count : 0

  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-rt-${local.azs[count.index]}"
  })
}

resource "aws_route_table_association" "firewall" {
  count = var.enable_portal_inspection ? var.az_count : 0

  subnet_id      = aws_subnet.firewall[count.index].id
  route_table_id = aws_route_table.firewall[count.index].id
}

# ------------------------------------------------------------------------------
# Stateful rule group: portal-anomalies (ALERT-only baseline)
# ------------------------------------------------------------------------------
# Suricata-style ALERTs on protocols with no legitimate east-west use in the
# portal. Visibility-first: nothing is dropped here, so a misconfiguration
# does not break a deploy. FLOW logs from the firewall capture the rest.

resource "aws_networkfirewall_rule_group" "portal_anomalies" {
  count = var.enable_portal_inspection ? 1 : 0

  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.cloudwatch_logs.arn
  }

  capacity = 100
  name     = "${var.name_prefix}-portal-anomalies"
  type     = "STATEFUL"

  rule_group {
    rule_variables {
      ip_sets {
        key = "HOME_NET"
        ip_set {
          definition = [var.vpc_cidr]
        }
      }
    }

    rules_source {
      rules_string = <<-EOT
        alert tcp $HOME_NET any -> $HOME_NET 22 (msg:"Portal east-west SSH (unexpected)"; flow:to_server,established; sid:1100001; rev:1;)
        alert tcp $HOME_NET any -> $HOME_NET 3389 (msg:"Portal east-west RDP (unexpected)"; flow:to_server,established; sid:1100002; rev:1;)
        alert icmp $HOME_NET any -> $HOME_NET any (msg:"Portal east-west ICMP (unexpected)"; sid:1100003; rev:1;)
      EOT
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-anomalies"
  })
}

# ------------------------------------------------------------------------------
# Firewall policy
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_firewall_policy" "portal" {
  count = var.enable_portal_inspection ? 1 : 0

  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.cloudwatch_logs.arn
  }

  name = "${var.name_prefix}-portal-firewall-policy"

  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:forward_to_sfe"]

    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.portal_anomalies[0].arn
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-firewall-policy"
  })
}

# ------------------------------------------------------------------------------
# Firewall instance (multi-AZ via subnet_mapping)
# ------------------------------------------------------------------------------
# CKV2_AWS_63 (firewall logging cross-resource): logging is wired via the
# separate aws_networkfirewall_logging_configuration below. Reuses the same
# ADR-004-R11 exception class as the range firewall.

resource "aws_networkfirewall_firewall" "portal" {
  # checkov:skip=CKV2_AWS_63:Logging defined in aws_networkfirewall_logging_configuration.portal below.
  count = var.enable_portal_inspection ? 1 : 0

  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.cloudwatch_logs.arn
  }

  name                = "${var.name_prefix}-portal-firewall"
  firewall_policy_arn = aws_networkfirewall_firewall_policy.portal[0].arn
  vpc_id              = aws_vpc.this.id
  delete_protection   = true

  dynamic "subnet_mapping" {
    for_each = aws_subnet.firewall
    content {
      subnet_id = subnet_mapping.value.id
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-firewall"
  })

  lifecycle {
    precondition {
      condition     = !var.enable_portal_inspection || var.enable_log_aggregation
      error_message = "enable_portal_inspection requires enable_log_aggregation = true so firewall FLOW / ALERT logs reach the existing log-aggregation pipeline. Either enable aggregation or disable portal inspection."
    }
  }
}

# ------------------------------------------------------------------------------
# CloudWatch logging (FLOW + ALERT)
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "firewall" {
  count = var.enable_portal_inspection ? 1 : 0

  name              = "/aws/network-firewall/${var.name_prefix}-portal"
  retention_in_days = var.firewall_log_retention_days
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-firewall-logs"
  })
}

resource "aws_networkfirewall_logging_configuration" "portal" {
  count = var.enable_portal_inspection ? 1 : 0

  firewall_arn = aws_networkfirewall_firewall.portal[0].arn

  logging_configuration {
    log_destination_config {
      log_destination = {
        logGroup = aws_cloudwatch_log_group.firewall[0].name
      }
      log_destination_type = "CloudWatchLogs"
      log_type             = "ALERT"
    }

    log_destination_config {
      log_destination = {
        logGroup = aws_cloudwatch_log_group.firewall[0].name
      }
      log_destination_type = "CloudWatchLogs"
      log_type             = "FLOW"
    }
  }
}

# ------------------------------------------------------------------------------
# Complete-matrix east-west and egress routing
# ------------------------------------------------------------------------------
# Every public route table installs a more-specific route to EVERY private
# subnet CIDR via that public RT's same-AZ firewall endpoint, and every
# private route table installs the symmetric route to every public subnet
# CIDR via that private RT's same-AZ firewall endpoint. With ALB's
# always-on cross-zone load balancing and a single shared NAT, public and
# private traffic can legitimately cross AZs in either direction;
# routing only the same-index pair through the firewall would let those
# cross-AZ flows fall back to the implicit local VPC route and bypass
# inspection entirely. The complete matrix closes that bypass: every
# public<->private flow traverses some firewall endpoint in each direction
# and gets logged + rule-evaluated.
#
# Stateful trade-off (acknowledged):
#   For cross-AZ flows the forward and return legs traverse different
#   per-AZ firewall endpoints (each AZ's RT steers through its own
#   endpoint). The flow is therefore inspected asymmetrically: each
#   endpoint sees one direction. This is compatible with the v1 policy
#   (visibility-first: stateful default pass + ALERT-only rules + FLOW
#   logs) because the rule set fires per-packet on whichever endpoint
#   observes the packet, and FLOW logs from both endpoints together
#   reconstruct the flow. It would not be compatible with a stateful
#   drop-by-default policy that requires session symmetry; that posture
#   would require a centralized inspection topology (single endpoint via
#   Transit Gateway, GWLB with consistent hashing, or single-AZ portal
#   appliance), all of which are larger architecture changes deferred
#   beyond this issue.
#
# Egress shape:
#   - Private egress out:  AZ-private -> AZ-firewall endpoint -> shared
#     NAT -> IGW (private RT default 0/0 -> AZ-firewall endpoint; firewall
#     RT default 0/0 -> the shared NAT gateway).
#   - NAT return in:  IGW -> NAT (in public_subnet[0]) -> public RT for
#     NAT's AZ -> firewall endpoint for THAT AZ -> destination private
#     subnet. For private destinations in other AZs the return is
#     therefore inspected by the NAT-AZ endpoint while the outbound
#     leg was inspected by the source-AZ endpoint. The direct
#     private->NAT default in main.tf is disabled when
#     enable_portal_inspection = true so the path is uniformly
#     private -> firewall -> NAT outbound.

locals {
  # Build a map of availability_zone -> firewall endpoint id from the
  # firewall's sync_states. Each sync_states entry corresponds to one
  # subnet_mapping entry, keyed by its AZ, with the endpoint id under
  # attachment.endpoint_id.
  firewall_endpoint_ids_by_az = var.enable_portal_inspection ? {
    for s in tolist(aws_networkfirewall_firewall.portal[0].firewall_status[0].sync_states) :
    s.availability_zone => tolist(s.attachment)[0].endpoint_id
  } : {}

  # Cartesian product of route-table index (which AZ's RT) x destination
  # subnet index (which AZ's subnet CIDR). Each pair becomes one route on
  # the route-table-AZ's same-AZ firewall endpoint pointed at the
  # destination AZ's subnet CIDR — including the same-index pair, which
  # remains the dominant in-AZ flow.
  az_pairs = setproduct(range(var.az_count), range(var.az_count))
}

resource "aws_route" "public_to_private_via_firewall" {
  count = var.enable_portal_inspection ? length(local.az_pairs) : 0

  route_table_id         = aws_route_table.public[local.az_pairs[count.index][0]].id
  destination_cidr_block = aws_subnet.private[local.az_pairs[count.index][1]].cidr_block
  vpc_endpoint_id        = local.firewall_endpoint_ids_by_az[local.azs[local.az_pairs[count.index][0]]]
}

resource "aws_route" "private_to_public_via_firewall" {
  count = var.enable_portal_inspection ? length(local.az_pairs) : 0

  route_table_id         = aws_route_table.private[local.az_pairs[count.index][0]].id
  destination_cidr_block = aws_subnet.public[local.az_pairs[count.index][1]].cidr_block
  vpc_endpoint_id        = local.firewall_endpoint_ids_by_az[local.azs[local.az_pairs[count.index][0]]]
}

# Per-AZ private egress default: send 0.0.0.0/0 from the private tier
# through the same-AZ firewall endpoint instead of straight to NAT. Pairs
# with the firewall RT default below so the path is private -> firewall
# -> NAT -> IGW.
resource "aws_route" "private_default_via_firewall" {
  count = var.enable_portal_inspection && var.enable_nat_gateway ? var.az_count : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  vpc_endpoint_id        = local.firewall_endpoint_ids_by_az[local.azs[count.index]]
}

# Per-AZ firewall-subnet egress default: from the firewall endpoint, send
# onward Internet-bound traffic to the existing shared NAT gateway.
resource "aws_route" "firewall_default_via_nat" {
  count = var.enable_portal_inspection && var.enable_nat_gateway ? var.az_count : 0

  route_table_id         = aws_route_table.firewall[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}
