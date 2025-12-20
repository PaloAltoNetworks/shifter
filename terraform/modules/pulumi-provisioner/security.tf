# ------------------------------------------------------------------------------
# ECS Task Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "ecs_task" {
  name        = "${var.name_prefix}-pulumi-ecs-sg"
  description = "Security group for Pulumi provisioner ECS tasks"
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
  description              = "PostgreSQL from Pulumi ECS tasks"
}
