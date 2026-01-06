# ------------------------------------------------------------------------------
# Application Load Balancer for Guacamole Web Client
# ------------------------------------------------------------------------------
# Creates:
# - Application Load Balancer (public subnets)
# - ACM certificate (DNS validation)
# - Target group with health check
# - HTTPS listener (443) with ACM cert
# - HTTP listener (80) redirects to HTTPS
# - WAF Web ACL with AWS managed rules (optional)

# ------------------------------------------------------------------------------
# ACM Certificate
# ------------------------------------------------------------------------------

resource "aws_acm_certificate" "guacamole" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-cert"
  })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "guacamole" {
  certificate_arn = aws_acm_certificate.guacamole.arn

  timeouts {
    create = "45m"
  }
}

# ------------------------------------------------------------------------------
# Application Load Balancer
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_150:Deletion protection deferred for dev flexibility
resource "aws_lb" "guacamole" {
  name                       = "${var.name_prefix}-guacamole-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true

  access_logs {
    bucket  = var.logs_bucket_name
    prefix  = "alb/${var.name_prefix}-guacamole"
    enabled = var.enable_access_logs && var.logs_bucket_name != ""
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-alb"
  })
}

# ------------------------------------------------------------------------------
# Target Group
# ------------------------------------------------------------------------------

resource "aws_lb_target_group" "guacamole" {
  name        = "${var.name_prefix}-guac-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

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

  # Enable stickiness for WebSocket connections
  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-tg"
  })
}

# ------------------------------------------------------------------------------
# Listeners
# ------------------------------------------------------------------------------

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.guacamole.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.guacamole.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.guacamole.arn
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.guacamole.arn
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

# ------------------------------------------------------------------------------
# WAF Web ACL
# ------------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "guacamole" {
  count = var.enable_waf ? 1 : 0

  name        = "${var.name_prefix}-guacamole-waf"
  description = "WAF for Guacamole ALB"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # Rate limiting - 2000 requests per 5 minutes per IP
  rule {
    name     = "RateLimitRule"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-guacamole-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # AWS Managed Rules - IP Reputation List
  rule {
    name     = "AWSManagedRulesAmazonIpReputationList"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-guacamole-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  # AWS Managed Rules - Known Bad Inputs
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-guacamole-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # AWS Managed Rules - Common Rule Set (OWASP Top 10)
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-guacamole-common-rules"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-guacamole-waf"
    sampled_requests_enabled   = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-waf"
  })
}

# Associate WAF with ALB
resource "aws_wafv2_web_acl_association" "guacamole" {
  count = var.enable_waf ? 1 : 0

  resource_arn = aws_lb.guacamole.arn
  web_acl_arn  = aws_wafv2_web_acl.guacamole[0].arn
}
