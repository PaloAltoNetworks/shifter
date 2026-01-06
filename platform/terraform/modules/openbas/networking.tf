# OpenBAS Networking
#
# Creates:
# - Private subnets across AZs for HA deployment
# - Security groups for ECS tasks
# - Route table associations

# ------------------------------------------------------------------------------
# OpenBAS Private Subnets
# ------------------------------------------------------------------------------
# Allocated in the infrastructure block of Range VPC (10.1.0.0/24)
# Using /27 subnets (32 IPs each) starting at 10.1.0.64
# - AZ1: 10.1.0.64/27 (cidrsubnet index 4 with /11 newbits from base + 4)
# - AZ2: 10.1.0.96/27

resource "aws_subnet" "openbas" {
  count = local.az_count

  vpc_id                  = var.vpc_id
  cidr_block              = cidrsubnet(var.vpc_cidr, 11, 2 + count.index) # 10.1.0.64/27, 10.1.0.96/27
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-${count.index + 1}"
    Tier = "private"
    AZ   = local.azs[count.index]
  })
}

# ------------------------------------------------------------------------------
# Route Table Associations
# ------------------------------------------------------------------------------
# Associate OpenBAS subnets with the existing private route table
# Traffic flows through Network Firewall -> NAT -> IGW

resource "aws_route_table_association" "openbas" {
  count = local.az_count

  subnet_id      = aws_subnet.openbas[count.index].id
  route_table_id = var.private_route_table_id
}

# ------------------------------------------------------------------------------
# ECS Task Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "ecs" {
  name        = "${var.name_prefix}-openbas-ecs"
  description = "Security group for OpenBAS ECS tasks"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-ecs-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# Ingress from Portal ALB (via VPC peering)
# Portal ALB forwards /shifter-mirage/bas/* to this target group
resource "aws_security_group_rule" "ecs_from_portal_alb" {
  type              = "ingress"
  from_port         = 8080
  to_port           = 8080
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.ecs.id
  description       = "HTTP from Portal ALB (via VPC peering)"
}

# Egress to RDS
resource "aws_security_group_rule" "ecs_to_rds" {
  type                     = "egress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rds.id
  security_group_id        = aws_security_group.ecs.id
  description              = "PostgreSQL to RDS"
}

# Egress HTTPS for S3, ECR, CloudWatch, Secrets Manager
resource "aws_security_group_rule" "ecs_https_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs.id
  description       = "HTTPS for AWS services and container registry"
}

# Egress DNS
resource "aws_security_group_rule" "ecs_dns_udp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs.id
  description       = "DNS UDP"
}

resource "aws_security_group_rule" "ecs_dns_tcp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs.id
  description       = "DNS TCP"
}

# ------------------------------------------------------------------------------
# RDS Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "rds" {
  name        = "${var.name_prefix}-openbas-rds"
  description = "Security group for OpenBAS RDS PostgreSQL"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-rds-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# Ingress from ECS tasks
resource "aws_security_group_rule" "rds_from_ecs" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs.id
  security_group_id        = aws_security_group.rds.id
  description              = "PostgreSQL from ECS tasks"
}

# Egress (required for RDS)
resource "aws_security_group_rule" "rds_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.rds.id
  description       = "Allow all outbound"
}
