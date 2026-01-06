# OpenBAS Target Group
#
# Creates target group for attachment to Portal ALB.
# Route: /shifter-mirage/bas/* -> OpenBAS ECS tasks
#
# The listener rule is created in the Portal environment where the ALB lives.

# ------------------------------------------------------------------------------
# Target Group (for Portal ALB)
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
