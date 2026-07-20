# In-VPC split-horizon DNS for range egress containment (#1172).
#
# Range hosts use AmazonProvidedDNS (VPC CIDR + 2). Route 53 Resolver DNS
# Firewall allowlists scenario-required and bootstrap suffixes and blocks
# everything else, closing the DNS exfil/C2 lane without opening UDP/TCP 53
# to public recursive resolvers.

locals {
  vpc_dns_server = cidrhost(var.vpc_cidr, 2)

  # victim_allowed_domains / range_dns_allowed_domains are leading-dot suffixes
  # (e.g. ".amazonaws.com"), the format Network Firewall's TLS_SNI/HTTP_HOST
  # matcher accepts. Route 53 Resolver DNS Firewall rejects leading dots and
  # instead expects a bare apex plus an explicit "*." wildcard for subdomains,
  # so normalize each suffix into both forms (".amazonaws.com" ->
  # ["amazonaws.com", "*.amazonaws.com"]). Trailing dots are stripped so the
  # apex form is well-formed.
  resolver_allowed_domains = distinct(flatten([
    for d in concat(var.victim_allowed_domains, var.range_dns_allowed_domains) : [
      trimsuffix(trimprefix(d, "."), "."),
      "*.${trimsuffix(trimprefix(d, "."), ".")}",
    ]
  ]))
}

# ------------------------------------------------------------------------------
# VPC DHCP — point range instances at AmazonProvidedDNS
# ------------------------------------------------------------------------------

resource "aws_vpc_dhcp_options" "this" {
  domain_name_servers = [local.vpc_dns_server]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dhcp-options"
  })
}

resource "aws_vpc_dhcp_options_association" "this" {
  vpc_id          = aws_vpc.this.id
  dhcp_options_id = aws_vpc_dhcp_options.this.id
}

# ------------------------------------------------------------------------------
# Route 53 Resolver DNS Firewall
# ------------------------------------------------------------------------------

resource "aws_route53_resolver_firewall_domain_list" "allowed" {
  count = var.enable_network_firewall ? 1 : 0

  name    = "${var.name_prefix}-dns-allowed-domains"
  domains = local.resolver_allowed_domains

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dns-allowed-domains"
  })
}

resource "aws_route53_resolver_firewall_domain_list" "catch_all" {
  count = var.enable_network_firewall ? 1 : 0

  name    = "${var.name_prefix}-dns-catch-all"
  domains = ["*"]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dns-catch-all"
  })
}

resource "aws_route53_resolver_firewall_rule_group" "range_dns" {
  count = var.enable_network_firewall ? 1 : 0

  name = "${var.name_prefix}-dns-firewall"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dns-firewall"
  })
}

resource "aws_route53_resolver_firewall_rule" "allow_listed" {
  count = var.enable_network_firewall ? 1 : 0

  name                    = "allow-scenario-domains"
  action                  = "ALLOW"
  firewall_domain_list_id = aws_route53_resolver_firewall_domain_list.allowed[0].id
  firewall_rule_group_id  = aws_route53_resolver_firewall_rule_group.range_dns[0].id
  priority                = 100
}

resource "aws_route53_resolver_firewall_rule" "block_unlisted" {
  count = var.enable_network_firewall ? 1 : 0

  name                    = "block-unlisted-external"
  action                  = "BLOCK"
  block_response          = "NODATA"
  firewall_domain_list_id = aws_route53_resolver_firewall_domain_list.catch_all[0].id
  firewall_rule_group_id  = aws_route53_resolver_firewall_rule_group.range_dns[0].id
  priority                = 200
}

resource "aws_route53_resolver_firewall_config" "this" {
  count = var.enable_network_firewall ? 1 : 0

  resource_id        = aws_vpc.this.id
  firewall_fail_open = "DISABLED"
}

resource "aws_route53_resolver_firewall_rule_group_association" "this" {
  count = var.enable_network_firewall ? 1 : 0

  name                   = "${var.name_prefix}-dns-firewall-assoc"
  firewall_rule_group_id = aws_route53_resolver_firewall_rule_group.range_dns[0].id
  # Rule-group association priority must be within the non-reserved band
  # 101-9899 (AWS reserves the 100 / 9900 boundaries); 1000 keeps room on both
  # sides for future associations.
  priority = 1000
  vpc_id   = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dns-firewall-assoc"
  })
}

# ------------------------------------------------------------------------------
# Resolver query logging
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "dns_resolver" {
  count = var.enable_network_firewall ? 1 : 0

  name              = "/aws/route53/resolver/${var.name_prefix}"
  retention_in_days = var.firewall_log_retention_days
  kms_key_id        = aws_kms_key.range_vpc.arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dns-resolver-logs"
  })
}

resource "aws_route53_resolver_query_log_config" "this" {
  count = var.enable_network_firewall ? 1 : 0

  name            = "${var.name_prefix}-dns-query-logs"
  destination_arn = aws_cloudwatch_log_group.dns_resolver[0].arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dns-query-logs"
  })
}

resource "aws_route53_resolver_query_log_config_association" "this" {
  count = var.enable_network_firewall ? 1 : 0

  resolver_query_log_config_id = aws_route53_resolver_query_log_config.this[0].id
  resource_id                  = aws_vpc.this.id
}
