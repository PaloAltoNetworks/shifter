# AWS Network Firewall for Range VPC Egress Filtering
#
# Filters outbound traffic from Kali and Victim instances using domain allowlists.
# - Kali: NO external access (VPC internal only via security groups)
# - Victim: XDR/XSIAM endpoints only
#
# Traffic flow: User Subnet -> Firewall -> NAT Gateway -> IGW -> Internet

# ------------------------------------------------------------------------------
# Firewall Subnet (10.1.0.0/28)
# ------------------------------------------------------------------------------

resource "aws_subnet" "firewall" {
  count = var.enable_network_firewall ? 1 : 0

  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 12, 0) # 10.1.0.0/28
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-subnet"
    Tier = "firewall"
  })
}

# ------------------------------------------------------------------------------
# Firewall Route Table
# ------------------------------------------------------------------------------

resource "aws_route_table" "firewall" {
  count = var.enable_network_firewall ? 1 : 0

  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-rt"
  })
}

# Traffic from firewall goes to NAT Gateway
resource "aws_route" "firewall_to_nat" {
  count = var.enable_network_firewall ? 1 : 0

  route_table_id         = aws_route_table.firewall[0].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}

resource "aws_route_table_association" "firewall" {
  count = var.enable_network_firewall ? 1 : 0

  subnet_id      = aws_subnet.firewall[0].id
  route_table_id = aws_route_table.firewall[0].id
}

# ------------------------------------------------------------------------------
# Network Firewall Rule Groups
# ------------------------------------------------------------------------------

# Victim domain allowlist - XDR/XSIAM endpoints only
resource "aws_networkfirewall_rule_group" "victim_domains" {
  count = var.enable_network_firewall ? 1 : 0

  capacity = 100
  name     = "${var.name_prefix}-victim-domains"
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
      rules_source_list {
        generated_rules_type = "ALLOWLIST"
        target_types         = ["TLS_SNI", "HTTP_HOST"]
        targets              = var.victim_allowed_domains
      }
    }

    # Use DEFAULT_ACTION_ORDER so domain allowlist works correctly
    # STRICT_ORDER with drop_strict drops TCP SYN before TLS SNI can be inspected
    stateful_rule_options {
      rule_order = "DEFAULT_ACTION_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-domains"
  })
}

# Kali domain allowlist - empty by default (Kali has full tools, no external access needed)
resource "aws_networkfirewall_rule_group" "kali_domains" {
  count = var.enable_network_firewall && length(var.kali_allowed_domains) > 0 ? 1 : 0

  capacity = 100
  name     = "${var.name_prefix}-kali-domains"
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
      rules_source_list {
        generated_rules_type = "ALLOWLIST"
        target_types         = ["TLS_SNI", "HTTP_HOST"]
        targets              = var.kali_allowed_domains
      }
    }

    # Use DEFAULT_ACTION_ORDER so domain allowlist works correctly
    stateful_rule_options {
      rule_order = "DEFAULT_ACTION_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-kali-domains"
  })
}

# ------------------------------------------------------------------------------
# Block Direct IP Connections (no hostname/SNI bypass)
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_rule_group" "block_ip_sni" {
  count = var.enable_network_firewall ? 1 : 0

  capacity = 10
  name     = "${var.name_prefix}-block-ip-sni"
  type     = "STATEFUL"

  rule_group {
    rule_variables {
      ip_sets {
        key = "HOME_NET"
        ip_set {
          definition = [var.vpc_cidr]
        }
      }
      ip_sets {
        key = "EXTERNAL_NET"
        ip_set {
          definition = ["0.0.0.0/0"]
        }
      }
    }

    rules_source {
      # Suricata rule to reject TLS connections where SNI is an IP address
      # This prevents bypassing domain allowlist by connecting directly to IPs
      rules_string = <<-EOT
        reject tls $HOME_NET any -> $EXTERNAL_NET any (tls.sni; content:"."; pcre:"/^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$/"; msg:"Blocked: IP address used as TLS SNI"; sid:1000001; rev:1;)
      EOT
    }

    stateful_rule_options {
      rule_order = "DEFAULT_ACTION_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-block-ip-sni"
  })
}

# ------------------------------------------------------------------------------
# Network Firewall Policy
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_firewall_policy" "this" {
  count = var.enable_network_firewall ? 1 : 0

  name = "${var.name_prefix}-firewall-policy"

  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:forward_to_sfe"]

    # Use DEFAULT_ACTION_ORDER for domain-based filtering
    # This allows TCP handshake to complete so TLS SNI can be inspected
    stateful_engine_options {
      rule_order = "DEFAULT_ACTION_ORDER"
    }

    # With DEFAULT_ACTION_ORDER, unmatched traffic is dropped after rules are evaluated
    # This allows the domain allowlist to work properly

    # Block direct IP connections
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.block_ip_sni[0].arn
    }

    # Victim domains (always included)
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.victim_domains[0].arn
    }

    # Kali domains (only if configured)
    dynamic "stateful_rule_group_reference" {
      for_each = length(var.kali_allowed_domains) > 0 ? [1] : []
      content {
        resource_arn = aws_networkfirewall_rule_group.kali_domains[0].arn
      }
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-policy"
  })
}

# ------------------------------------------------------------------------------
# Network Firewall
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_firewall" "this" {
  count = var.enable_network_firewall ? 1 : 0

  name                = "${var.name_prefix}-firewall"
  firewall_policy_arn = aws_networkfirewall_firewall_policy.this[0].arn
  vpc_id              = aws_vpc.this.id

  subnet_mapping {
    subnet_id = aws_subnet.firewall[0].id
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall"
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Logging
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "firewall" {
  count = var.enable_network_firewall ? 1 : 0

  name              = "/aws/network-firewall/${var.name_prefix}"
  retention_in_days = var.firewall_log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-logs"
  })
}

resource "aws_networkfirewall_logging_configuration" "this" {
  count = var.enable_network_firewall ? 1 : 0

  firewall_arn = aws_networkfirewall_firewall.this[0].arn

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
# Private Route Table (for user subnets)
# ------------------------------------------------------------------------------

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-private-rt"
  })
}

# Route to firewall when enabled, otherwise to NAT directly
resource "aws_route" "private_to_firewall" {
  count = var.enable_network_firewall ? 1 : 0

  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  vpc_endpoint_id        = one(one(aws_networkfirewall_firewall.this[0].firewall_status).sync_states).attachment[0].endpoint_id
}

# Fallback route to NAT when firewall is disabled
resource "aws_route" "private_to_nat" {
  count = var.enable_network_firewall ? 0 : 1

  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}
