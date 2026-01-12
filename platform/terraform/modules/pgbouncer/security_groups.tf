# ------------------------------------------------------------------------------
# PgBouncer Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "pgbouncer" {
  name        = "${var.name_prefix}-pgbouncer-sg"
  description = "Security group for PgBouncer ECS tasks"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer-sg"
  })
}

# Ingress from Portal EC2 on port 5432 (PostgreSQL)
resource "aws_security_group_rule" "pgbouncer_from_portal" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = var.portal_security_group_id
  security_group_id        = aws_security_group.pgbouncer.id
  description              = "PostgreSQL from Portal EC2"
}

# Ingress from additional clients (e.g., Pulumi provisioner ECS tasks)
resource "aws_security_group_rule" "pgbouncer_from_additional" {
  for_each = toset(var.additional_client_security_group_ids)

  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = each.value
  security_group_id        = aws_security_group.pgbouncer.id
  description              = "PostgreSQL from additional client"
}

# Egress to RDS on port 5432
resource "aws_security_group_rule" "pgbouncer_to_rds" {
  type                     = "egress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = var.rds_security_group_id
  security_group_id        = aws_security_group.pgbouncer.id
  description              = "PostgreSQL to RDS"
}

# Egress for HTTPS (AWS APIs - CloudWatch, Secrets Manager)
resource "aws_security_group_rule" "pgbouncer_https_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.pgbouncer.id
  description       = "HTTPS to AWS APIs"
}

# Egress for DNS (UDP)
resource "aws_security_group_rule" "pgbouncer_dns_udp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.pgbouncer.id
  description       = "DNS resolution (UDP)"
}

# Egress for DNS (TCP)
resource "aws_security_group_rule" "pgbouncer_dns_tcp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.pgbouncer.id
  description       = "DNS resolution (TCP)"
}

# ------------------------------------------------------------------------------
# RDS Security Group Rule - Allow PgBouncer
# ------------------------------------------------------------------------------
# Add ingress rule to RDS security group to allow PgBouncer

resource "aws_security_group_rule" "rds_from_pgbouncer" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.pgbouncer.id
  security_group_id        = var.rds_security_group_id
  description              = "PostgreSQL from PgBouncer"
}
