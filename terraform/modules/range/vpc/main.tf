# Range VPC Module
#
# Stable infrastructure for per-user range subnets.
# Creates VPC, IGW, NAT Gateway, Network Firewall, and private route table.
# User subnets are ephemeral (created by provisioner Lambda).
#
# Traffic flow: User Subnet -> Network Firewall -> NAT Gateway -> IGW -> Internet
# Domain-based egress filtering via AWS Network Firewall allowlists.

locals {
  common_tags = merge(var.tags, {
    Module = "range-vpc"
  })
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_12:Default SG restriction deferred - see #221
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpc"
  })
}

# ------------------------------------------------------------------------------
# Internet Gateway
# ------------------------------------------------------------------------------

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-igw"
  })
}

# ------------------------------------------------------------------------------
# Route Tables - See nat.tf and firewall.tf
# ------------------------------------------------------------------------------
# - aws_route_table.private (in firewall.tf) - User subnets route through firewall
# - aws_route_table.firewall (in firewall.tf) - Firewall routes to NAT
# - aws_route_table.nat (in nat.tf) - NAT routes to IGW

# ------------------------------------------------------------------------------
# Victim Security Group (shared by all victim EC2 instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned EC2 instances
# Note: All rules defined as standalone aws_security_group_rule resources below
# to avoid conflicts between inline rules and standalone rules.
resource "aws_security_group" "victim" {
  name        = "${var.name_prefix}-victim"
  description = "Security group for victim EC2 instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Kali Security Group (shared by all Kali attack instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned EC2 instances
# Note: All rules defined as standalone aws_security_group_rule resources below
# to avoid conflicts between inline rules and standalone rules.
resource "aws_security_group" "kali" {
  name        = "${var.name_prefix}-kali"
  description = "Security group for Kali attack EC2 instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-kali-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Victim Security Group Rules
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "victim_ssh_from_portal" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.victim.id
  description       = "SSH from Portal VPC (browser terminal)"
}

resource "aws_security_group_rule" "victim_from_kali" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.kali.id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic from Kali"
}

# When NGFW is enabled, traffic arrives at Victim from NGFW (not directly from Kali)
resource "aws_security_group_rule" "victim_from_ngfw" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.ngfw[0].id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic from NGFW (forwarded attacks)"
}

resource "aws_security_group_rule" "victim_to_kali" {
  type                     = "egress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.kali.id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic to Kali (reverse shells)"
}

# When NGFW is enabled, Victim sends return traffic to NGFW (not directly to Kali)
resource "aws_security_group_rule" "victim_to_ngfw" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type                     = "egress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.ngfw[0].id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic to NGFW (return traffic)"
}

resource "aws_security_group_rule" "victim_https_to_vpc" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.victim.id
  description       = "HTTPS to VPC (SSM endpoints)"
}

resource "aws_security_group_rule" "victim_https_to_internet" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.victim.id
  description       = "HTTPS for XDR (filtered by ANFW)"
}

resource "aws_security_group_rule" "victim_dns_udp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.victim.id
  description       = "DNS UDP"
}

resource "aws_security_group_rule" "victim_dns_tcp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.victim.id
  description       = "DNS TCP"
}

resource "aws_security_group_rule" "victim_to_dc" {
  count = var.enable_dc_security_group ? 1 : 0

  type                     = "egress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.dc[0].id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic to DC (domain join, AD services)"
}

# ------------------------------------------------------------------------------
# NGFW Security Group (shared by all VM-Series NGFW instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned NGFW instances
# Note: All rules defined as standalone aws_security_group_rule resources below
# to avoid conflicts between inline rules and standalone rules.
resource "aws_security_group" "ngfw" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  name        = "${var.name_prefix}-ngfw"
  description = "Security group for VM-Series NGFW instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# NGFW Security Group Rules
# ------------------------------------------------------------------------------

# All traffic from Kali (attack traffic entering NGFW)
resource "aws_security_group_rule" "ngfw_from_kali" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.kali.id
  security_group_id        = aws_security_group.ngfw[0].id
  description              = "All traffic from Kali (attack traffic)"
}

# All traffic from Victim (return traffic)
resource "aws_security_group_rule" "ngfw_from_victim" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.victim.id
  security_group_id        = aws_security_group.ngfw[0].id
  description              = "All traffic from Victim (return traffic)"
}

# SSH from Portal VPC (management access via browser terminal)
resource "aws_security_group_rule" "ngfw_ssh_from_portal" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.ngfw[0].id
  description       = "SSH from Portal VPC (management)"
}

# HTTPS from Portal VPC (management web UI)
resource "aws_security_group_rule" "ngfw_https_from_portal" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.ngfw[0].id
  description       = "HTTPS from Portal VPC (management web UI)"
}

# All traffic to VPC (forward to victim, return to kali)
resource "aws_security_group_rule" "ngfw_to_vpc" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.ngfw[0].id
  description       = "All traffic to VPC (forwarding)"
}

# HTTPS egress for telemetry to Panorama/Cloud
resource "aws_security_group_rule" "ngfw_https_to_internet" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ngfw[0].id
  description       = "HTTPS for telemetry (filtered by ANFW)"
}

# DNS for NGFW operations
resource "aws_security_group_rule" "ngfw_dns_udp" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ngfw[0].id
  description       = "DNS UDP"
}

resource "aws_security_group_rule" "ngfw_dns_tcp" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ngfw[0].id
  description       = "DNS TCP"
}

# ------------------------------------------------------------------------------
# Kali Security Group Rules
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "kali_ssh_from_portal" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.kali.id
  description       = "SSH from Portal VPC (browser terminal)"
}

resource "aws_security_group_rule" "kali_from_victim" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.victim.id
  security_group_id        = aws_security_group.kali.id
  description              = "All traffic from victim (reverse shells)"
}

# When NGFW is enabled, return traffic arrives at Kali from NGFW (not directly from Victim)
resource "aws_security_group_rule" "kali_from_ngfw" {
  count = var.vm_series_ami_id != "" ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.ngfw[0].id
  security_group_id        = aws_security_group.kali.id
  description              = "All traffic from NGFW (return traffic)"
}

resource "aws_security_group_rule" "kali_to_vpc" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.kali.id
  description       = "All traffic to VPC (attack victim)"
}

resource "aws_security_group_rule" "kali_dns_udp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.kali.id
  description       = "DNS UDP"
}

resource "aws_security_group_rule" "kali_dns_tcp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.kali.id
  description       = "DNS TCP"
}

resource "aws_security_group_rule" "kali_to_dc" {
  count = var.enable_dc_security_group ? 1 : 0

  type                     = "egress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.dc[0].id
  security_group_id        = aws_security_group.kali.id
  description              = "All traffic to DC (AD attacks)"
}

# ------------------------------------------------------------------------------
# Domain Controller Security Group (for AD/DC instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned DC instances
resource "aws_security_group" "dc" {
  count = var.enable_dc_security_group ? 1 : 0

  name        = "${var.name_prefix}-dc"
  description = "Security group for Domain Controller EC2 instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-dc-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# DC Security Group Rules - Ingress (AD Services from VPC)
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "dc_ssh_from_portal" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "SSH from Portal VPC (browser terminal)"
}

resource "aws_security_group_rule" "dc_rdp_from_range" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 3389
  to_port           = 3389
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "RDP from Range VPC"
}

resource "aws_security_group_rule" "dc_ldap_tcp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 389
  to_port           = 389
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "LDAP TCP from VPC"
}

resource "aws_security_group_rule" "dc_ldap_udp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 389
  to_port           = 389
  protocol          = "udp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "LDAP UDP from VPC"
}

resource "aws_security_group_rule" "dc_ldaps" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 636
  to_port           = 636
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "LDAPS from VPC"
}

resource "aws_security_group_rule" "dc_dns_tcp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "DNS TCP from VPC"
}

resource "aws_security_group_rule" "dc_dns_udp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "DNS UDP from VPC"
}

resource "aws_security_group_rule" "dc_kerberos_tcp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 88
  to_port           = 88
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "Kerberos TCP from VPC"
}

resource "aws_security_group_rule" "dc_kerberos_udp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 88
  to_port           = 88
  protocol          = "udp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "Kerberos UDP from VPC"
}

resource "aws_security_group_rule" "dc_smb" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 445
  to_port           = 445
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "SMB from VPC"
}

resource "aws_security_group_rule" "dc_global_catalog" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 3268
  to_port           = 3268
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "Global Catalog from VPC"
}

resource "aws_security_group_rule" "dc_global_catalog_ssl" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 3269
  to_port           = 3269
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "Global Catalog SSL from VPC"
}

resource "aws_security_group_rule" "dc_rpc_endpoint_mapper" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 135
  to_port           = 135
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "RPC Endpoint Mapper from VPC"
}

resource "aws_security_group_rule" "dc_rpc_dynamic" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 49152
  to_port           = 65535
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "Dynamic RPC from VPC (required for AD replication and management)"
}

resource "aws_security_group_rule" "dc_ntp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "ingress"
  from_port         = 123
  to_port           = 123
  protocol          = "udp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "NTP from VPC"
}

resource "aws_security_group_rule" "dc_from_kali" {
  count = var.enable_dc_security_group ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.kali.id
  security_group_id        = aws_security_group.dc[0].id
  description              = "All traffic from Kali (for AD attack scenarios)"
}

resource "aws_security_group_rule" "dc_from_victim" {
  count = var.enable_dc_security_group ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.victim.id
  security_group_id        = aws_security_group.dc[0].id
  description              = "All traffic from Victim (domain join, lateral movement)"
}

# ------------------------------------------------------------------------------
# DC Security Group Rules - Egress
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "dc_to_vpc" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.dc[0].id
  description       = "All traffic to VPC (AD services to domain members)"
}

resource "aws_security_group_rule" "dc_dns_egress_udp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.dc[0].id
  description       = "DNS UDP for forwarders (AWS DNS at 169.254.169.253)"
}

resource "aws_security_group_rule" "dc_dns_egress_tcp" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.dc[0].id
  description       = "DNS TCP for forwarders"
}

resource "aws_security_group_rule" "dc_https_egress" {
  count = var.enable_dc_security_group ? 1 : 0

  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.dc[0].id
  description       = "HTTPS for Windows Update and AWS APIs"
}

# ------------------------------------------------------------------------------
# Kali/Victim Ingress from DC (for reverse shells and lateral movement)
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "kali_all_from_dc" {
  count = var.enable_dc_security_group ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.dc[0].id
  security_group_id        = aws_security_group.kali.id
  description              = "All traffic from DC (reverse shells, lateral movement)"
}

resource "aws_security_group_rule" "victim_all_from_dc" {
  count = var.enable_dc_security_group ? 1 : 0

  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.dc[0].id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic from DC (lateral movement scenarios)"
}

# ------------------------------------------------------------------------------
# VPC Flow Logs
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name              = "/vpc/${var.name_prefix}-flow-logs"
  retention_in_days = var.firewall_log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-logs"
  })
}

resource "aws_iam_role" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name = "${var.name_prefix}-flow-logs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "vpc-flow-logs.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name = "${var.name_prefix}-flow-logs-policy"
  role = aws_iam_role.flow_logs[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_flow_log" "main" {
  count = var.enable_flow_logs ? 1 : 0

  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow_logs[0].arn
  iam_role_arn         = aws_iam_role.flow_logs[0].arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-log"
  })
}
