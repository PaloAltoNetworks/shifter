# ALB Module - Application Load Balancer for Django portal
#
# Creates:
# - Application Load Balancer (public subnets)
# - ACM certificate (DNS validation)
# - Target group with health check
# - HTTPS listener (443) with ACM cert
# - HTTP listener (80) redirects to HTTPS
# - Security group (80/443 from internet)

locals {
  common_tags = merge(var.tags, {
    Module = "alb"
  })
}

# ------------------------------------------------------------------------------
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-alb-sg"
  description = "Security group for ALB"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-alb-sg"
  })
}

resource "aws_security_group_rule" "http_ingress" {
  type              = "ingress"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.this.id
  description       = "HTTP from internet"
}

resource "aws_security_group_rule" "https_ingress" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.this.id
  description       = "HTTPS from internet"
}

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.this.id
  description       = "Allow all outbound"
}

# ------------------------------------------------------------------------------
# ACM Certificate
# ------------------------------------------------------------------------------

resource "aws_acm_certificate" "this" {
  domain_name               = var.domain_name
  subject_alternative_names = ["chat.${var.domain_name}"]
  validation_method         = "DNS"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-cert"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# ACM Certificate Validation
# ------------------------------------------------------------------------------

resource "aws_acm_certificate_validation" "this" {
  certificate_arn = aws_acm_certificate.this.arn

  timeouts {
    create = "45m"
  }
}

# ------------------------------------------------------------------------------
# Application Load Balancer
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_150:Deletion protection deferred - see #214
# checkov:skip=CKV_AWS_91:Access logs deferred - see #57, #58
# checkov:skip=CKV2_AWS_28:WAF deferred - see #52
resource "aws_lb" "this" {
  name                       = "${var.name_prefix}-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.this.id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-alb"
  })
}

# ------------------------------------------------------------------------------
# Target Group
# ------------------------------------------------------------------------------

resource "aws_lb_target_group" "this" {
  name     = "${var.name_prefix}-tg"
  port     = var.app_port
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = var.health_check_path
    protocol            = "HTTP"
    matcher             = "200"
  }

  dynamic "stickiness" {
    for_each = var.enable_stickiness ? [1] : []
    content {
      type            = "lb_cookie"
      cookie_duration = 86400
      enabled         = true
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-tg"
  })
}

# Target group attachment is handled externally in the environment
# to avoid circular dependency: EC2 needs ALB SG ID, ALB would need EC2 ID

# ------------------------------------------------------------------------------
# Listeners
# ------------------------------------------------------------------------------

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.this.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }

  tags = local.common_tags
}

# Block /admin from public access - only accessible via SSM tunnel
resource "aws_lb_listener_rule" "block_admin" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 1

  action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }

  condition {
    path_pattern {
      values = ["/admin", "/admin/*"]
    }
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }

  tags = local.common_tags
}
