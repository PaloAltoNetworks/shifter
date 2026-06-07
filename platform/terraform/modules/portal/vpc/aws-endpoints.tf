# Private AWS service endpoints for portal runtime bootstrap.
#
# The portal private tier routes default egress through the inspection firewall
# and NAT path. Fresh-account applies can start ECS tasks and EC2 user_data while
# that egress path is still settling; Fargate then fails before containers start
# because ECR auth, image layer pulls, Secrets Manager reads, and awslogs setup
# all happen during task initialization. These endpoints keep required AWS API
# traffic on the VPC-local path and remove that race from initial bootstrap.

data "aws_region" "current" {}

locals {
  gateway_endpoint_services = toset([
    "dynamodb",
    "s3",
  ])

  interface_endpoint_services = toset([
    "ec2",
    "ec2messages",
    "ecr.api",
    "ecr.dkr",
    "ecs",
    "elasticloadbalancing",
    "kms",
    "logs",
    "secretsmanager",
    "sns",
    "sqs",
    "ssm",
    "ssmmessages",
    "sts",
  ])
}

resource "aws_vpc_endpoint" "gateway" {
  for_each = local.gateway_endpoint_services

  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.id}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-${each.key}-endpoint"
  })
}

resource "aws_security_group" "interface_endpoints" {
  name        = "${var.name_prefix}-aws-endpoints-sg"
  description = "Security group for portal private AWS service endpoints"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-aws-endpoints-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "interface_endpoints_https_from_vpc" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.interface_endpoints.id
  description       = "HTTPS from portal VPC workloads"
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.interface_endpoint_services

  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.id}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.interface_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-${replace(each.key, ".", "-")}-endpoint"
  })
}
