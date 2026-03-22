# ------------------------------------------------------------------------------
# ECS Task Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "ecs_task" {
  name        = "${var.name_prefix}-pulumi-ecs-sg"
  description = "Security group for engine provisioner ECS tasks"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-ecs-sg"
  })
}

# ------------------------------------------------------------------------------
# Egress Rules
# ------------------------------------------------------------------------------

# HTTPS egress for AWS APIs
resource "aws_security_group_rule" "ecs_https_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs_task.id
  description       = "HTTPS to AWS APIs"
}

# DNS egress for hostname resolution (required for AWS API endpoints, RDS, etc.)
resource "aws_security_group_rule" "ecs_dns_udp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs_task.id
  description       = "DNS resolution (UDP)"
}

resource "aws_security_group_rule" "ecs_dns_tcp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ecs_task.id
  description       = "DNS resolution (TCP for large responses)"
}

# PostgreSQL egress to RDS
resource "aws_security_group_rule" "ecs_to_rds" {
  type                     = "egress"
  from_port                = var.db_port
  to_port                  = var.db_port
  protocol                 = "tcp"
  source_security_group_id = var.rds_security_group_id
  security_group_id        = aws_security_group.ecs_task.id
  description              = "PostgreSQL to RDS"
}

# SSH egress to Range VPC for NGFW provisioning
resource "aws_security_group_rule" "ecs_ssh_to_range" {
  type              = "egress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.range_vpc_cidr]
  security_group_id = aws_security_group.ecs_task.id
  description       = "SSH to Range VPC for NGFW provisioning"
}

# ------------------------------------------------------------------------------
# RDS Ingress Rule (allow ECS to connect)
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "rds_from_ecs" {
  type                     = "ingress"
  from_port                = var.db_port
  to_port                  = var.db_port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_task.id
  security_group_id        = var.rds_security_group_id
  description              = "PostgreSQL from engine ECS tasks"
}
