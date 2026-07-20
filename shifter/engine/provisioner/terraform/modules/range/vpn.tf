# Request-owned OpenVPN termination for one authorized Kali target.
# Credential values are created by the provisioner directly in Secrets Manager;
# this module receives no certificate, key, profile, or secret-reference input.

data "aws_partition" "current" {}
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  vpn_target_keys = var.openvpn_access == null ? [] : [
    for key, instance in local.instance_map : key
    if instance.instance_uuid == var.openvpn_access.target_ref
  ]
  vpn_enabled = (
    var.openvpn_access != null &&
    length(local.vpn_target_keys) == 1 &&
    var.vpn_edge_subnet_id != "" &&
    var.vpn_gateway_permissions_boundary_arn != "" &&
    var.vpn_provider_endpoint_security_group_id != "" &&
    var.portal_vpc_cidr != ""
  )
  vpn_target_key       = local.vpn_enabled ? one(local.vpn_target_keys) : null
  vpn_secret_name      = "shifter/${var.environment}/range/${var.range_id}/vpn-${var.request_uuid}-server"
  vpn_gateway_role     = "shifter-${var.environment}-range-${var.range_id}-vpn-gateway"
  vpn_gateway_tag_name = "shifter-vpn-${var.range_id}"
}

check "openvpn_capability_target" {
  assert {
    condition     = var.openvpn_access == null || length(local.vpn_target_keys) == 1
    error_message = "The server-issued OpenVPN capability must identify exactly one range member."
  }
}

check "openvpn_capability_prerequisites" {
  assert {
    condition = var.openvpn_access == null || (
      var.openvpn_access.version == "openvpn-capability-v1" &&
      var.openvpn_access.channel == "openvpn" &&
      var.vpn_edge_subnet_id != "" &&
      var.vpn_gateway_permissions_boundary_arn != "" &&
      var.vpn_provider_endpoint_security_group_id != "" &&
      var.portal_vpc_cidr != ""
    )
    error_message = "The authorized OpenVPN capability cannot be realized by this AWS adapter."
  }
}

resource "aws_iam_role" "vpn_gateway" {
  count = local.vpn_enabled ? 1 : 0

  name                 = substr(local.vpn_gateway_role, 0, 64)
  permissions_boundary = var.vpn_gateway_permissions_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = merge(local.common_tags, {
    Name              = local.vpn_gateway_tag_name
    "shifter:purpose" = "openvpn-gateway"
  })
}

resource "aws_iam_role_policy" "vpn_gateway" {
  count = local.vpn_enabled ? 1 : 0

  name = "read-generation-server-identity"
  role = aws_iam_role.vpn_gateway[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadOnlyOwnServerIdentity"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:${data.aws_partition.current.partition}:secretsmanager:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:secret:${local.vpn_secret_name}-*"
      },
      {
        Sid      = "DecryptOnlyThroughSecretsManager"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = var.secrets_kms_key_arn
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${data.aws_region.current.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "vpn_gateway_ssm" {
  count = local.vpn_enabled ? 1 : 0

  role       = aws_iam_role.vpn_gateway[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "vpn_gateway" {
  count = local.vpn_enabled ? 1 : 0

  name = substr(local.vpn_gateway_role, 0, 64)
  role = aws_iam_role.vpn_gateway[0].name
  tags = local.common_tags
}

resource "aws_security_group" "vpn_gateway" {
  count = local.vpn_enabled ? 1 : 0

  name        = "shifter-range-${var.range_id}-vpn-gateway"
  description = "Target-only OpenVPN gateway for range ${var.range_id}"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, { Name = local.vpn_gateway_tag_name })
}

resource "aws_security_group" "vpn_nlb" {
  count = local.vpn_enabled ? 1 : 0

  name        = "shifter-range-${var.range_id}-vpn-nlb"
  description = "Public UDP ingress for range ${var.range_id} OpenVPN"
  vpc_id      = var.vpc_id

  ingress {
    protocol    = "udp"
    from_port   = 1194
    to_port     = 1194
    cidr_blocks = [var.vpn_public_client_cidr]
    description = "Mutual-TLS OpenVPN ingress"
  }

  egress {
    protocol        = "udp"
    from_port       = 1194
    to_port         = 1194
    security_groups = [aws_security_group.vpn_gateway[0].id]
    description     = "Forward only to this range gateway"
  }

  egress {
    protocol        = "tcp"
    from_port       = 1195
    to_port         = 1195
    security_groups = [aws_security_group.vpn_gateway[0].id]
    description     = "OpenVPN service and policy health check"
  }

  tags = merge(local.common_tags, { Name = "${local.vpn_gateway_tag_name}-nlb" })
}

resource "aws_security_group_rule" "vpn_gateway_from_nlb" {
  count = local.vpn_enabled ? 1 : 0

  type                     = "ingress"
  protocol                 = "udp"
  from_port                = 1194
  to_port                  = 1194
  security_group_id        = aws_security_group.vpn_gateway[0].id
  source_security_group_id = aws_security_group.vpn_nlb[0].id
  description              = "OpenVPN only from the range NLB"
}

resource "aws_security_group_rule" "vpn_gateway_health_from_nlb" {
  count = local.vpn_enabled ? 1 : 0

  type                     = "ingress"
  protocol                 = "tcp"
  from_port                = 1195
  to_port                  = 1195
  security_group_id        = aws_security_group.vpn_gateway[0].id
  source_security_group_id = aws_security_group.vpn_nlb[0].id
  description              = "NLB OpenVPN service and policy health check"
}

resource "aws_security_group_rule" "vpn_gateway_health_from_portal" {
  count = local.vpn_enabled && var.portal_vpc_cidr != "" ? 1 : 0

  type              = "ingress"
  protocol          = "tcp"
  from_port         = 1195
  to_port           = 1195
  security_group_id = aws_security_group.vpn_gateway[0].id
  cidr_blocks       = [var.portal_vpc_cidr]
  description       = "Private provisioner service and policy readiness probe"
}

resource "aws_security_group_rule" "vpn_gateway_target_only" {
  count = local.vpn_enabled ? 1 : 0

  type              = "egress"
  protocol          = "-1"
  from_port         = 0
  to_port           = 0
  security_group_id = aws_security_group.vpn_gateway[0].id
  cidr_blocks       = ["${aws_instance.range[local.vpn_target_key].private_ip}/32"]
  description       = "Only the authorized Kali target"
}

resource "aws_security_group_rule" "vpn_gateway_provider_api" {
  count = local.vpn_enabled ? 1 : 0

  type                     = "egress"
  protocol                 = "tcp"
  from_port                = 443
  to_port                  = 443
  security_group_id        = aws_security_group.vpn_gateway[0].id
  source_security_group_id = var.vpn_provider_endpoint_security_group_id
  description              = "Private provider API endpoints only"
}

resource "aws_security_group_rule" "vpn_gateway_dns_udp" {
  count = local.vpn_enabled ? 1 : 0

  type              = "egress"
  protocol          = "udp"
  from_port         = 53
  to_port           = 53
  security_group_id = aws_security_group.vpn_gateway[0].id
  cidr_blocks       = [var.vpc_cidr]
  description       = "VPC DNS only"
}

resource "aws_instance" "vpn_gateway" {
  count = local.vpn_enabled ? 1 : 0

  ami                         = var.victim_ami_id
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.range[local.instance_map[local.vpn_target_key].subnet_name].id
  vpc_security_group_ids      = [aws_security_group.vpn_gateway[0].id]
  iam_instance_profile        = aws_iam_instance_profile.vpn_gateway[0].name
  source_dest_check           = false
  associate_public_ip_address = false
  user_data_base64 = base64encode(templatefile("${path.module}/templates/openvpn_gateway_aws.py.tpl", {
    environment  = var.environment
    range_id     = var.range_id
    request_uuid = var.request_uuid
    target_ip    = aws_instance.range[local.vpn_target_key].private_ip
  }))

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    encrypted = true
  }

  tags = merge(local.common_tags, {
    Name                  = local.vpn_gateway_tag_name
    "shifter:role"        = "vpn-gateway"
    "shifter:target_uuid" = local.instance_map[local.vpn_target_key].instance_uuid
    "shifter:credential"  = "openvpn-server"
  })

  depends_on = [
    aws_iam_role_policy.vpn_gateway,
    aws_iam_role_policy_attachment.vpn_gateway_ssm,
  ]
}

# NLB access logs only record TLS-listener traffic; this NLB fronts a UDP/1194
# OpenVPN listener, so enabling them would produce an empty log bucket.
# Connection-level visibility comes from VPC Flow Logs on the edge subnet.
resource "aws_lb" "vpn" { # NOSONAR — S6258: access logs are a TLS-only NLB feature, listener is UDP-only
  count = local.vpn_enabled ? 1 : 0

  name                             = substr("shifter-vpn-${var.range_id}-${substr(var.request_uuid, 0, 8)}", 0, 32)
  internal                         = false
  load_balancer_type               = "network"
  subnets                          = [var.vpn_edge_subnet_id]
  security_groups                  = [aws_security_group.vpn_nlb[0].id]
  enable_cross_zone_load_balancing = false

  tags = merge(local.common_tags, { Name = "${local.vpn_gateway_tag_name}-nlb" })
}

resource "aws_lb_target_group" "vpn" {
  count = local.vpn_enabled ? 1 : 0

  name        = substr("shifter-vpn-${var.range_id}-${substr(var.request_uuid, 0, 8)}", 0, 32)
  port        = 1194
  protocol    = "UDP"
  target_type = "instance"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    protocol            = "TCP"
    port                = "1195"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
  }

  tags = local.common_tags
}

resource "aws_lb_target_group_attachment" "vpn" {
  count = local.vpn_enabled ? 1 : 0

  target_group_arn = aws_lb_target_group.vpn[0].arn
  target_id        = aws_instance.vpn_gateway[0].id
  port             = 1194
}

resource "aws_lb_listener" "vpn" {
  count = local.vpn_enabled ? 1 : 0

  load_balancer_arn = aws_lb.vpn[0].arn
  port              = 1194
  protocol          = "UDP"

  tags = local.common_tags

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.vpn[0].arn
  }
}
