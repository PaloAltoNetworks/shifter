# NGFW Infrastructure for Persistent Per-User NGFW Instances
#
# Creates shared infrastructure for persistent NGFW instances:
# - Dedicated /22 subnet (1024 IPs, ~500 NGFW capacity with 2 IPs each)
# - Management security group (SSH, HTTPS for management)
# - Dataplane security group (all traffic from VPC via GWLB)
# - IAM role for NGFW bootstrap (S3 read, CloudWatch logs)
#
# See GitHub issue #408 for full design.

# ------------------------------------------------------------------------------
# NGFW Subnet (10.1.4.0/22 - 1024 IPs for ~500 NGFWs)
# ------------------------------------------------------------------------------
# Using cidrsubnet with newbits=6 and index=1 to avoid overlap with:
# - 10.1.0.0/28 (firewall)
# - 10.1.0.16/28 (NAT)
# - 10.1.0.32/28 (SSM endpoints)

resource "aws_subnet" "ngfw" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 6, 1) # 10.1.4.0/22
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-subnet"
    Tier = "ngfw"
  })
}

# Associate with private route table
resource "aws_route_table_association" "ngfw" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  subnet_id      = aws_subnet.ngfw[0].id
  route_table_id = aws_route_table.private.id
}

# ------------------------------------------------------------------------------
# NGFW Management Security Group
# ------------------------------------------------------------------------------
# Controls access to NGFW management interfaces (SSH, HTTPS web UI)

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned NGFW instances
resource "aws_security_group" "ngfw_mgmt" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name        = "${var.name_prefix}-ngfw-mgmt"
  description = "Security group for NGFW management interfaces"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-mgmt-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# SSH from Portal VPC (management access)
resource "aws_security_group_rule" "ngfw_mgmt_ssh_from_portal" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.ngfw_mgmt[0].id
  description       = "SSH from Portal VPC (management)"
}

# HTTPS from Portal VPC (management web UI)
resource "aws_security_group_rule" "ngfw_mgmt_https_from_portal" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.ngfw_mgmt[0].id
  description       = "HTTPS from Portal VPC (management web UI)"
}

# Outbound: All (for SCM/licensing communication)
resource "aws_security_group_rule" "ngfw_mgmt_egress_all" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ngfw_mgmt[0].id
  description       = "All egress for SCM/licensing"
}

# ------------------------------------------------------------------------------
# NGFW Dataplane Security Group
# ------------------------------------------------------------------------------
# Controls traffic through NGFW dataplane interfaces (GENEVE via GWLB)

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned NGFW instances
resource "aws_security_group" "ngfw_data" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name        = "${var.name_prefix}-ngfw-data"
  description = "Security group for NGFW dataplane interfaces"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-data-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# Inbound: All from VPC (GENEVE traffic from GWLB)
resource "aws_security_group_rule" "ngfw_data_ingress_vpc" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  type              = "ingress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.ngfw_data[0].id
  description       = "All traffic from VPC (GENEVE via GWLB)"
}

# Outbound: All (for inspected traffic egress)
resource "aws_security_group_rule" "ngfw_data_egress_all" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ngfw_data[0].id
  description       = "All egress for inspected traffic"
}

# ------------------------------------------------------------------------------
# NGFW Instance IAM Role
# ------------------------------------------------------------------------------
# Provides NGFW instances with access to:
# - S3 bootstrap bucket for init-cfg.txt and authcode
# - CloudWatch Logs for debugging

resource "aws_iam_role" "ngfw_instance" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name = "${var.name_prefix}-ngfw-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-instance"
  })
}

# S3 read access for bootstrap configuration
resource "aws_iam_role_policy" "ngfw_instance_s3" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name = "s3-bootstrap-read"
  role = aws_iam_role.ngfw_instance[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = "arn:aws:s3:::${var.agent_s3_bucket}/ngfw-bootstrap/*"
      }
    ]
  })
}

# CloudWatch Logs access for debugging
resource "aws_iam_role_policy" "ngfw_instance_logs" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name = "cloudwatch-logs"
  role = aws_iam_role.ngfw_instance[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:log-group:/shifter/ngfw/*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ngfw_instance" {
  count = var.enable_ngfw_infrastructure ? 1 : 0

  name = "${var.name_prefix}-ngfw-instance"
  role = aws_iam_role.ngfw_instance[0].name

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ngfw-instance"
  })
}
