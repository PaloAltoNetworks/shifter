# Provisioner Lambda Security Groups
#
# Lambda functions need:
# - Egress to RDS (port 5432)
# - Egress to AWS APIs (HTTPS)

# ------------------------------------------------------------------------------
# Lambda Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "lambda" {
  name        = "${var.name_prefix}-provisioner-lambda-sg"
  description = "Security group for provisioner Lambda functions"
  vpc_id      = var.portal_vpc_id

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provisioner-lambda-sg"
    Module = "provisioner"
  })
}

# Egress to RDS
resource "aws_security_group_rule" "lambda_to_rds" {
  type                     = "egress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = var.rds_security_group_id
  security_group_id        = aws_security_group.lambda.id
  description              = "PostgreSQL to RDS"
}

# Egress to HTTPS (AWS APIs via NAT Gateway)
resource "aws_security_group_rule" "lambda_to_https" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.lambda.id
  description       = "HTTPS for AWS APIs"
}

# ------------------------------------------------------------------------------
# Allow Lambda to connect to RDS
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "rds_from_lambda" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  security_group_id        = var.rds_security_group_id
  description              = "PostgreSQL from provisioner Lambda"
}
