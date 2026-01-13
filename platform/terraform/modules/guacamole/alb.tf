# ------------------------------------------------------------------------------
# Guacamole Target Group and Listener Rule (Shared Portal ALB)
# ------------------------------------------------------------------------------
# Uses the Portal ALB instead of a dedicated ALB. Creates:
# - Target group for guacamole-client ECS tasks
# - Listener rule on Portal ALB for /guacamole/* path

# ------------------------------------------------------------------------------
# Target Group
# ------------------------------------------------------------------------------

resource "aws_lb_target_group" "guacamole" {
  name        = "${var.name_prefix}-guacamole"
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
    path                = "/guacamole/"
    protocol            = "HTTP"
    matcher             = "200,302"
  }

  # Enable stickiness for WebSocket connections
  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400 # 24 hours
    enabled         = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-tg"
  })
}

# ------------------------------------------------------------------------------
# Listener Rule on Portal ALB
# ------------------------------------------------------------------------------

resource "aws_lb_listener_rule" "guacamole" {
  listener_arn = var.alb_listener_arn
  priority     = 100 # Before default action

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.guacamole.arn
  }

  condition {
    path_pattern {
      values = ["/guacamole/*", "/guacamole"]
    }
  }

  tags = local.common_tags
}
