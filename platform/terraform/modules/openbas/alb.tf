# OpenBAS Application Load Balancer
#
# Creates:
# - Internal ALB for API and agent traffic
# - ACM certificate (DNS validation)
# - Target group with health check
# - HTTPS listener

# ------------------------------------------------------------------------------
# ACM Certificate
# ------------------------------------------------------------------------------

resource "aws_acm_certificate" "openbas" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-cert"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "openbas" {
  certificate_arn = aws_acm_certificate.openbas.arn

  timeouts {
    create = "45m"
  }
}

# ------------------------------------------------------------------------------
# Application Load Balancer (Internal)
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_150:Deletion protection configurable
resource "aws_lb" "openbas" {
  name                       = "${var.name_prefix}-openbas"
  internal                   = true # Internal ALB - not internet-facing
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.openbas[*].id
  drop_invalid_header_fields = true

  access_logs {
    bucket  = var.logs_bucket_name
    prefix  = "alb/${var.name_prefix}-openbas"
    enabled = var.enable_alb_access_logs && var.logs_bucket_name != ""
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-alb"
  })
}

# ------------------------------------------------------------------------------
# Target Group
# ------------------------------------------------------------------------------

resource "aws_lb_target_group" "openbas" {
  name        = "${var.name_prefix}-openbas"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Required for Fargate

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    path                = "/api/health"
    protocol            = "HTTP"
    matcher             = "200"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-tg"
  })
}

# ------------------------------------------------------------------------------
# Listeners
# ------------------------------------------------------------------------------

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.openbas.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.openbas.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.openbas.arn
  }

  tags = local.common_tags
}

# HTTP listener for redirect (agent compatibility)
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.openbas.arn
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
