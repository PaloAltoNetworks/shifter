# ALB Routing for MCP and Chat UI
# This contract defines the ALB configuration for routing /chat/* to AgentChat

# Target group for AgentChat EC2 (OpenWebUI + MCP)
resource "aws_lb_target_group" "agentchat" {
  name     = "${var.name_prefix}-agentchat"
  port     = 3000  # OpenWebUI port
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "${var.name_prefix}-agentchat"
  }
}

# Target group for MCP endpoint
resource "aws_lb_target_group" "mcp" {
  name     = "${var.name_prefix}-mcp"
  port     = 3001  # MCP server port
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "${var.name_prefix}-mcp"
  }
}

# Listener rule: /chat/* → AgentChat (OpenWebUI)
resource "aws_lb_listener_rule" "chat" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.agentchat.arn
  }

  condition {
    path_pattern {
      values = ["/chat", "/chat/*"]
    }
  }
}

# Listener rule: /mcp/* → MCP server
resource "aws_lb_listener_rule" "mcp" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 99  # Higher priority than /chat

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mcp.arn
  }

  condition {
    path_pattern {
      values = ["/mcp", "/mcp/*"]
    }
  }
}

# Register AgentChat EC2 with target groups
resource "aws_lb_target_group_attachment" "agentchat" {
  target_group_arn = aws_lb_target_group.agentchat.arn
  target_id        = aws_instance.agentchat.id
  port             = 3000
}

resource "aws_lb_target_group_attachment" "mcp" {
  target_group_arn = aws_lb_target_group.mcp.arn
  target_id        = aws_instance.agentchat.id
  port             = 3001
}
