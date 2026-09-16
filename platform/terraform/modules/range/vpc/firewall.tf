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
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

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

    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-domains"
  })
}

# Kali domain allowlist - empty by default (Kali has full tools, no external access needed)
resource "aws_networkfirewall_rule_group" "kali_domains" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

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

    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-kali-domains"
  })
}

# ------------------------------------------------------------------------------
# NGFW Subnet Bypass - Allow all egress for SCM/licensing
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_rule_group" "ngfw_bypass" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

  count = var.enable_network_firewall && var.enable_ngfw_infrastructure ? 1 : 0

  capacity = 10
  name     = "${var.name_prefix}-ngfw-bypass"
  type     = "STATEFUL"

  rule_group {
    rules_source {
      # Pass all traffic from NGFW subnet - needed for SCM registration, licensing, content updates
      rules_string = <<-EOT
        pass ip ${cidrsubnet(var.vpc_cidr, 6, 1)} any -> any any (msg:"Allow NGFW subnet all egress"; sid:1000010; rev:1;)
      EOT
    }

    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-bypass"
  })
}

# ------------------------------------------------------------------------------
# Block Direct IP Connections (no hostname/SNI bypass)
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_rule_group" "block_ip_sni" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

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
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-block-ip-sni"
  })
}

# ------------------------------------------------------------------------------
# IP-based Allowlist (GCP ranges for PANW services)
#
# One STABLE stateful rule group holds the whole IP allowlist as multiple
# internal IP-set variables + pass rules (one per CIDR chunk). The AWS 8,192
# character limit is per EXPANDED Suricata rule, not per rule group, so chunking
# stays internal and the rule-group RESOURCE COUNT never tracks the CIDR count.
# Keeping cardinality stable is what makes an allowlist shrink an in-place
# content update rather than the destruction of a rule group the policy still
# references (#1134). The group is present whenever the firewall is present,
# including an empty allowlist (represented by an inert alert-only placeholder
# rule that cannot open an allow lane); default-deny is still enforced by
# drop_all at priority 100.
# ------------------------------------------------------------------------------

locals {
  # Split CIDRs into chunks of 300. Internal rendering detail that keeps each
  # expanded pass rule short; it does NOT change resource cardinality.
  cidr_chunk_size = 300
  cidr_chunks     = var.enable_network_firewall && length(var.victim_allowed_cidrs) > 0 ? chunklist(var.victim_allowed_cidrs, local.cidr_chunk_size) : []

  # One pass rule per chunk, each referencing that chunk's ALLOWED_IPS_<n>
  # variable. When the allowlist is empty, an inert alert-only placeholder
  # (destination RFC 5737 TEST-NET-1, never routed) keeps the group valid and
  # non-permitting so the group is present with a stable identity.
  victim_ips_rules_string = length(local.cidr_chunks) > 0 ? join("\n", [
    for i, _chunk in local.cidr_chunks :
    "pass tcp $HOME_NET any -> $ALLOWED_IPS_${i + 1} 443 (msg:\"Allow HTTPS to PANW/GCP IPs chunk ${i + 1}\"; sid:${2000001 + i}; rev:1;)"
  ]) : "alert tcp $HOME_NET any -> [192.0.2.0/24] 443 (msg:\"Range victim IP allowlist empty; no external IP egress permitted\"; sid:2000000; rev:1;)"
}

resource "aws_networkfirewall_rule_group" "victim_ips" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

  count = var.enable_network_firewall ? 1 : 0

  # Fixed capacity: `capacity` is ForceNew, so it must NOT track the CIDR count
  # (that would reintroduce a replacement/ordering event). Sized to hold the
  # realistic max total CIDRs (~1 unit/CIDR) while leaving headroom under the
  # 30k per-policy stateful aggregate for the domain/NTP/NGFW/drop groups.
  capacity = 10000
  name     = "${var.name_prefix}-victim-ips"
  type     = "STATEFUL"

  rule_group {
    rule_variables {
      ip_sets {
        key = "HOME_NET"
        ip_set {
          definition = [var.vpc_cidr]
        }
      }

      dynamic "ip_sets" {
        for_each = local.cidr_chunks
        content {
          key = "ALLOWED_IPS_${ip_sets.key + 1}"
          ip_set {
            definition = ip_sets.value
          }
        }
      }
    }

    rules_source {
      rules_string = local.victim_ips_rules_string
    }

    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-ips"
  })
}

# DNS egress is handled in dns_resolver.tf: hosts use AmazonProvidedDNS inside
# the VPC; Route 53 Resolver DNS Firewall allowlists scenario/bootstrap suffixes
# and blocks unknown external names. No UDP/TCP 53 egress to public resolvers.

# ------------------------------------------------------------------------------
# NTP Allow Rule (UDP 123 - required for time sync)
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_rule_group" "allow_ntp" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

  count = var.enable_network_firewall ? 1 : 0

  capacity = 10
  name     = "${var.name_prefix}-allow-ntp"
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
        pass udp $HOME_NET any -> any 123 (msg:"Allow NTP"; sid:1000030; rev:1;)
      EOT
    }

    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-allow-ntp"
  })
}

# ------------------------------------------------------------------------------
# Drop All Unmatched Traffic (default deny)
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_rule_group" "drop_all" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

  count = var.enable_network_firewall ? 1 : 0

  capacity = 10
  name     = "${var.name_prefix}-drop-all"
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
      # Drop ALL outbound traffic that wasn't explicitly allowed by previous rules
      # This enforces the allowlist - only traffic to allowed domains/IPs/DNS passes
      # CRITICAL: This blocks all protocols and ports, not just HTTP/HTTPS
      rules_string = <<-EOT
        drop ip $HOME_NET any -> $EXTERNAL_NET any (msg:"Drop all unmatched egress"; sid:9999999; rev:1;)
      EOT
    }

    stateful_rule_options {
      rule_order = "STRICT_ORDER"
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-drop-all"
  })
}

# ------------------------------------------------------------------------------
# Network Firewall Policy
# ------------------------------------------------------------------------------

resource "aws_networkfirewall_firewall_policy" "this" {
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

  count = var.enable_network_firewall ? 1 : 0

  # Renamed (and create_before_destroy below) to make the one-time migration from
  # the old per-chunk victim-ips-<n> rule groups ordering-safe (#1134). The name
  # change forces a policy REPLACEMENT: Terraform creates this new policy (which
  # references only the single stable victim_ips group), repoints the firewall to
  # it, destroys the old policy, and only then are the now-unreferenced old rule
  # groups destroyable — so the rollout apply never hits InvalidOperationException.
  name = "${var.name_prefix}-firewall-policy-v2"

  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:forward_to_sfe"]

    # Use STRICT_ORDER for predictable rule evaluation with priorities
    # Lower priority number = evaluated first
    stateful_engine_options {
      rule_order              = "STRICT_ORDER"
      stream_exception_policy = "CONTINUE"
    }

    # Rule evaluation order (STRICT_ORDER - lower priority evaluated first):
    # Priority 1: NGFW bypass - pass all from NGFW subnet
    # Priority 2: Victim IPs - allow HTTPS to GCP/PANW IP ranges (single group)
    # Priority 3: Victim domains - allow listed domains (SNI-based)
    # Priority 4: Kali domains - allow listed domains (if configured)
    # Priority 98: NTP allow
    # Priority 100: Drop all - drop ALL unmatched traffic (default deny)
    # DNS: no public-resolver egress rule; see dns_resolver.tf

    # NGFW bypass - allow all egress for SCM/licensing (priority 1)
    dynamic "stateful_rule_group_reference" {
      for_each = var.enable_ngfw_infrastructure ? [1] : []
      content {
        resource_arn = aws_networkfirewall_rule_group.ngfw_bypass[0].arn
        priority     = 1
      }
    }

    # Victim IPs - allow HTTPS to GCP/PANW IP ranges (single stable group,
    # priority 2). Every CIDR chunk lives inside this one group as internal
    # ALLOWED_IPS_<n> variables/rules, so the policy holds exactly ONE reference
    # regardless of allowlist size (#1134).
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.victim_ips[0].arn
      priority     = 2
    }

    # Victim domains - SNI-based allowlist (priority 3)
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.victim_domains[0].arn
      priority     = 3
    }

    # Kali domains (priority 4, only if configured)
    dynamic "stateful_rule_group_reference" {
      for_each = length(var.kali_allowed_domains) > 0 ? [1] : []
      content {
        resource_arn = aws_networkfirewall_rule_group.kali_domains[0].arn
        priority     = 4
      }
    }

    # NTP allow - allow NTP to any (priority 98)
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.allow_ntp[0].arn
      priority     = 98
    }

    # Drop all unmatched traffic (priority 100 - last, default deny)
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.drop_all[0].arn
      priority     = 100
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firewall-policy-v2"
  })

  # Create the replacement policy before destroying the old one so the firewall
  # can be repointed and the old policy retired before its (now-orphaned) rule
  # groups are destroyed. This is the ordering-safe migration boundary for #1134.
  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Network Firewall
# ------------------------------------------------------------------------------

# NF logging is wired via a separate aws_networkfirewall_logging_configuration
# resource (line 563), but Checkov's graph check cannot evaluate the cross-
# resource reference and flags this firewall as unlogged. See ADR-004-R11
# exception ckv2-aws-63-nf-logging-cross-resource.
resource "aws_networkfirewall_firewall" "this" {
  # checkov:skip=CKV2_AWS_63:Logging defined in aws_networkfirewall_logging_configuration "this" below.
  # checkov:skip=CKV_AWS_344:Deletion protection controlled by var.network_firewall_delete_protection (dev false / prod true). See ADR-004-R11 exception ckv-aws-344-nf-delete-protection.
  encryption_configuration {
    type   = "CUSTOMER_KMS"
    key_id = aws_kms_key.range_vpc.arn
  }

  count = var.enable_network_firewall ? 1 : 0

  name                = "${var.name_prefix}-firewall"
  firewall_policy_arn = aws_networkfirewall_firewall_policy.this[0].arn
  vpc_id              = aws_vpc.this.id
  delete_protection   = var.network_firewall_delete_protection

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
  kms_key_id        = aws_kms_key.range_vpc.arn

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
