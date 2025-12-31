# SSM VPC Endpoints for Range VPC
#
# Enables Systems Manager access for Kali and Victim instances without
# requiring internet access. Traffic stays within AWS network.
#
# Required endpoints:
# - ssm: Systems Manager API
# - ssmmessages: Session Manager messaging
# - ec2messages: EC2 run command messaging

# ------------------------------------------------------------------------------
# SSM Endpoints Subnet (10.1.0.32/28)
# ------------------------------------------------------------------------------

resource "aws_subnet" "ssm_endpoints" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 12, 2) # 10.1.0.32/28
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ssm-endpoints-subnet"
    Tier = "private"
  })
}

# Associate with private route table (no internet route needed for endpoints)
resource "aws_route_table_association" "ssm_endpoints" {
  subnet_id      = aws_subnet.ssm_endpoints.id
  route_table_id = aws_route_table.private.id
}

# ------------------------------------------------------------------------------
# Security Group for SSM Endpoints
# ------------------------------------------------------------------------------

# Note: All rules defined as standalone aws_security_group_rule resources
# to avoid conflicts between inline rules and standalone rules.
resource "aws_security_group" "ssm_endpoints" {
  name        = "${var.name_prefix}-ssm-endpoints"
  description = "Security group for SSM VPC endpoints"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ssm-endpoints-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "ssm_endpoints_https_from_vpc" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.ssm_endpoints.id
  description       = "HTTPS from VPC"
}

# ------------------------------------------------------------------------------
# SSM VPC Endpoints
# ------------------------------------------------------------------------------

# SSM API endpoint
resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.ssm_endpoints.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ssm-endpoint"
  })
}

# SSM Messages endpoint (for Session Manager)
resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.ssm_endpoints.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ssmmessages-endpoint"
  })
}

# EC2 Messages endpoint (for Run Command)
resource "aws_vpc_endpoint" "ec2messages" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.ssm_endpoints.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ec2messages-endpoint"
  })
}

# ------------------------------------------------------------------------------
# Bedrock VPC Endpoints (for Claude Code)
# ------------------------------------------------------------------------------

# Bedrock Runtime endpoint (for InvokeModel)
resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.ssm_endpoints.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-bedrock-runtime-endpoint"
  })
}

# STS endpoint (for credential refresh)
resource "aws_vpc_endpoint" "sts" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.sts"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.ssm_endpoints.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-sts-endpoint"
  })
}

# Data source for current region
data "aws_region" "current" {}
