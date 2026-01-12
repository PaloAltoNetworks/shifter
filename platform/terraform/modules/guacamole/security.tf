# ------------------------------------------------------------------------------
# Guacamole Client Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "guacamole_client" {
  name        = "${var.name_prefix}-guacamole-client-sg"
  description = "Security group for Guacamole client ECS tasks"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-client-sg"
  })
}

# Ingress from Portal ALB on port 8080 (Guacamole web interface)
resource "aws_security_group_rule" "guacamole_client_from_alb" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = var.alb_security_group_id
  security_group_id        = aws_security_group.guacamole_client.id
  description              = "HTTP from Portal ALB"
}

# Ingress from Portal EC2 on port 8080 (direct API calls for token generation)
resource "aws_security_group_rule" "guacamole_client_from_portal" {
  count = var.portal_security_group_id != "" ? 1 : 0

  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = var.portal_security_group_id
  security_group_id        = aws_security_group.guacamole_client.id
  description              = "HTTP from Portal EC2 (token API)"
}

# Egress to guacd on port 4822
resource "aws_security_group_rule" "guacamole_client_to_guacd" {
  type                     = "egress"
  from_port                = 4822
  to_port                  = 4822
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.guacd.id
  security_group_id        = aws_security_group.guacamole_client.id
  description              = "Guacamole protocol to guacd"
}

# Egress to RDS
resource "aws_security_group_rule" "guacamole_client_to_rds" {
  type                     = "egress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rds.id
  security_group_id        = aws_security_group.guacamole_client.id
  description              = "PostgreSQL to RDS"
}

# Egress for HTTPS (AWS APIs, ECR)
resource "aws_security_group_rule" "guacamole_client_https_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.guacamole_client.id
  description       = "HTTPS to AWS APIs"
}

# Egress for DNS
resource "aws_security_group_rule" "guacamole_client_dns_udp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.guacamole_client.id
  description       = "DNS resolution (UDP)"
}

resource "aws_security_group_rule" "guacamole_client_dns_tcp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.guacamole_client.id
  description       = "DNS resolution (TCP)"
}

# ------------------------------------------------------------------------------
# Guacd Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "guacd" {
  name        = "${var.name_prefix}-guacd-sg"
  description = "Security group for guacd ECS tasks"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacd-sg"
  })
}

# Ingress from guacamole-client on port 4822
resource "aws_security_group_rule" "guacd_from_client" {
  type                     = "ingress"
  from_port                = 4822
  to_port                  = 4822
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.guacamole_client.id
  security_group_id        = aws_security_group.guacd.id
  description              = "Guacamole protocol from client"
}

# Egress for RDP (port 3389) - to range instances
resource "aws_security_group_rule" "guacd_rdp_egress" {
  type              = "egress"
  from_port         = 3389
  to_port           = 3389
  protocol          = "tcp"
  cidr_blocks       = [var.range_vpc_cidr]
  security_group_id = aws_security_group.guacd.id
  description       = "RDP to range instances"
}

# Egress for VNC (ports 5900-5910)
resource "aws_security_group_rule" "guacd_vnc_egress" {
  type              = "egress"
  from_port         = 5900
  to_port           = 5910
  protocol          = "tcp"
  cidr_blocks       = [var.range_vpc_cidr]
  security_group_id = aws_security_group.guacd.id
  description       = "VNC to range instances"
}

# Egress for SSH (port 22)
resource "aws_security_group_rule" "guacd_ssh_egress" {
  type              = "egress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.range_vpc_cidr]
  security_group_id = aws_security_group.guacd.id
  description       = "SSH to range instances"
}

# Egress for HTTPS (AWS APIs, ECR)
resource "aws_security_group_rule" "guacd_https_egress" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.guacd.id
  description       = "HTTPS to AWS APIs"
}

# Egress for DNS
resource "aws_security_group_rule" "guacd_dns_udp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.guacd.id
  description       = "DNS resolution (UDP)"
}

resource "aws_security_group_rule" "guacd_dns_tcp_egress" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.guacd.id
  description       = "DNS resolution (TCP)"
}

# ------------------------------------------------------------------------------
# RDS Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "rds" {
  name        = "${var.name_prefix}-guacamole-rds-sg"
  description = "Security group for Guacamole RDS"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-rds-sg"
  })
}

# Ingress from guacamole-client
resource "aws_security_group_rule" "rds_from_guacamole_client" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.guacamole_client.id
  security_group_id        = aws_security_group.rds.id
  description              = "PostgreSQL from Guacamole client"
}
