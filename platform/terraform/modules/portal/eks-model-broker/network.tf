# Private peering preserves original guest source addresses. No proxy headers,
# Transit Gateway, public listener, or provider authority on the guest network.
resource "terraform_data" "boundary" {
  lifecycle {
    precondition {
      condition = (
        var.vpc_id != var.range_vpc_id &&
        cidrhost("${cidrhost(var.range_vpc_cidr, 0)}/${split("/", var.vpc_cidr)[1]}", 0) != cidrhost(var.vpc_cidr, 0) &&
        cidrhost("${cidrhost(var.vpc_cidr, 0)}/${split("/", var.range_vpc_cidr)[1]}", 0) != cidrhost(var.range_vpc_cidr, 0) &&
        alltrue([for subnet in var.settings.admitted_subnets :
          cidrhost("${cidrhost(subnet, 0)}/${split("/", var.range_vpc_cidr)[1]}", 0) == cidrhost(var.range_vpc_cidr, 0) && tonumber(split("/", subnet)[1]) >= tonumber(split("/", var.range_vpc_cidr)[1])
        ])
      )
      error_message = "Broker admits only range-owned subnets on a disjoint private network."
    }
  }
}

resource "aws_security_group" "endpoint" {
  name        = "${var.cluster_name}-model-provider"
  description = "TLS to private STS and Bedrock endpoints from EKS pods"
  vpc_id      = var.vpc_id
  tags        = var.tags
}
resource "aws_vpc_security_group_ingress_rule" "endpoint" {
  for_each          = var.private_subnets
  security_group_id = aws_security_group.endpoint.id
  cidr_ipv4         = each.value.cidr
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Private API transport; caller IAM and broker NetworkPolicy enforce authority"
}
resource "aws_vpc_endpoint" "provider" {
  for_each            = toset(["sts", "bedrock-runtime"])
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [for subnet in var.private_subnets : subnet.id]
  private_dns_enabled = true
  security_group_ids  = [aws_security_group.endpoint.id]
  tags                = var.tags
}

# Endpoint ENIs are addressed by deterministic service/AZ keys, so readback
# remains plannable even on the first apply. No public API CIDR fallback.
data "aws_network_interface" "endpoint" {
  for_each = { for pair in setproduct(["sts", "bedrock-runtime"], keys(var.private_subnets)) : "${pair[0]}/${pair[1]}" => pair }
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "subnet-id"
    values = [var.private_subnets[each.value[1]].id]
  }
  filter {
    name   = "network-interface-id"
    values = tolist(aws_vpc_endpoint.provider[each.value[0]].network_interface_ids)
  }
}

resource "aws_security_group" "listener" {
  name        = "${var.cluster_name}-model-listener"
  description = "Private guest TLS listener; admitted range subnets only"
  vpc_id      = var.vpc_id
  tags        = var.tags
}
resource "aws_vpc_security_group_ingress_rule" "listener" {
  for_each          = toset(var.settings.admitted_subnets)
  security_group_id = aws_security_group.listener.id
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "Model access from admitted guest subnets"
}
resource "aws_vpc_security_group_egress_rule" "listener" {
  for_each          = var.private_subnets
  security_group_id = aws_security_group.listener.id
  cidr_ipv4         = each.value.cidr
  ip_protocol       = "tcp"
  from_port         = 8443
  to_port           = 8443
  description       = "TLS passthrough and health checks to broker pods"
}
resource "aws_lb" "broker" {
  # checkov:skip=CKV_AWS_91:TCP passthrough preserves guest TLS; AWS NLB access logs require a TLS listener (ADR-004-R11).
  name                             = "${substr(var.cluster_name, 0, 19)}-model-broker"
  internal                         = true
  load_balancer_type               = "network"
  ip_address_type                  = "ipv4"
  subnets                          = [for subnet in var.private_subnets : subnet.id]
  security_groups                  = [aws_security_group.listener.id]
  enable_cross_zone_load_balancing = true
  enable_deletion_protection       = true
  tags                             = var.tags
}
# Read the actual private listener addresses after NLB creation. Guests receive
# only these /32 destinations, never the provider endpoint or whole pod subnet.
data "aws_network_interface" "listener" {
  for_each = var.private_subnets
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "subnet-id"
    values = [each.value.id]
  }
  filter {
    name   = "description"
    values = ["ELB ${aws_lb.broker.arn_suffix}"]
  }
}

resource "aws_lb_target_group" "broker" {
  name_prefix          = "model-"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  port                 = 8443
  protocol             = "TCP"
  preserve_client_ip   = true
  proxy_protocol_v2    = false
  deregistration_delay = 150
  health_check {
    protocol = "HTTPS"
    port     = "traffic-port"
    path     = "/health/ready"
    matcher  = "200"
  }
  tags = var.tags
  lifecycle { create_before_destroy = true }
}
resource "aws_lb_listener" "broker" {
  load_balancer_arn = aws_lb.broker.arn
  port              = 443
  protocol          = "TCP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.broker.arn
  }
  tags = var.tags
}
resource "aws_route53_zone" "broker" {
  name = var.settings.hostname
  vpc { vpc_id = var.vpc_id }
  vpc { vpc_id = var.range_vpc_id }
  tags = var.tags
}
resource "aws_route53_record" "broker" {
  zone_id = aws_route53_zone.broker.zone_id
  name    = var.settings.hostname
  type    = "A"
  alias {
    name                   = aws_lb.broker.dns_name
    zone_id                = aws_lb.broker.zone_id
    evaluate_target_health = true
  }
}
