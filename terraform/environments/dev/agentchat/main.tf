terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.environment}-agentchat"
}

# ------------------------------------------------------------------------------
# Remote State - Portal VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "portal" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "dev/portal/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# Remote State - Range VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "range" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "dev/range/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# Remote State - Foundation (ECR repos)
# ------------------------------------------------------------------------------

data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "dev/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# VPC Peering - Portal VPC to Range VPC
# ------------------------------------------------------------------------------

resource "aws_vpc_peering_connection" "portal_to_range" {
  vpc_id      = data.terraform_remote_state.portal.outputs.vpc_id
  peer_vpc_id = data.terraform_remote_state.range.outputs.vpc_id
  auto_accept = true

  accepter {
    allow_remote_vpc_dns_resolution = true
  }

  requester {
    allow_remote_vpc_dns_resolution = true
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-portal-range-peering"
  })
}

# Route from Portal private subnets to Range VPC
resource "aws_route" "portal_to_range" {
  route_table_id            = data.terraform_remote_state.portal.outputs.private_route_table_id
  destination_cidr_block    = data.terraform_remote_state.range.outputs.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Route from Range VPC to Portal VPC
resource "aws_route" "range_to_portal" {
  route_table_id            = data.terraform_remote_state.range.outputs.public_route_table_id
  destination_cidr_block    = data.terraform_remote_state.portal.outputs.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

module "ec2" {
  source = "../../../modules/agentchat/ec2"

  aws_region       = var.aws_region
  name_prefix      = local.name_prefix
  vpc_id           = data.terraform_remote_state.portal.outputs.vpc_id
  subnet_id        = data.terraform_remote_state.portal.outputs.private_subnet_ids[0]
  instance_type    = var.ec2_instance_type
  root_volume_size = var.ec2_root_volume_size

  # OpenWebUI PostgreSQL credentials (from Portal RDS)
  openwebui_db_secret_arn = data.terraform_remote_state.portal.outputs.openwebui_db_secret_arn

  # MCP server IAM permissions for RDS and Secrets Manager
  db_resource_id = data.terraform_remote_state.portal.outputs.db_resource_id
  environment    = var.environment

  # ECR pull permissions for mcp-shifter
  mcp_shifter_ecr_arn = data.terraform_remote_state.foundation.outputs.mcp_shifter_ecr_arn

  tags = var.tags
}

# ------------------------------------------------------------------------------
# ALB Target Group - OpenWebUI (/chat)
# ------------------------------------------------------------------------------

resource "aws_lb_target_group" "chat" {
  name     = "${local.name_prefix}-chat-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = data.terraform_remote_state.portal.outputs.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-chat-tg"
  })
}

resource "aws_lb_target_group_attachment" "chat" {
  target_group_arn = aws_lb_target_group.chat.arn
  target_id        = module.ec2.instance_id
  port             = 8080
}

# ------------------------------------------------------------------------------
# ALB Target Group - MCP Server (/mcp)
# ------------------------------------------------------------------------------

resource "aws_lb_target_group" "mcp" {
  name     = "${local.name_prefix}-mcp-tg"
  port     = 3001
  protocol = "HTTP"
  vpc_id   = data.terraform_remote_state.portal.outputs.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-mcp-tg"
  })
}

resource "aws_lb_target_group_attachment" "mcp" {
  target_group_arn = aws_lb_target_group.mcp.arn
  target_id        = module.ec2.instance_id
  port             = 3001
}

# ------------------------------------------------------------------------------
# ALB Listener Rules
# ------------------------------------------------------------------------------

resource "aws_lb_listener_rule" "chat" {
  listener_arn = data.terraform_remote_state.portal.outputs.alb_https_listener_arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.chat.arn
  }

  condition {
    path_pattern {
      values = ["/chat", "/chat/*"]
    }
  }

  tags = var.tags
}

resource "aws_lb_listener_rule" "mcp" {
  listener_arn = data.terraform_remote_state.portal.outputs.alb_https_listener_arn
  priority     = 11

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mcp.arn
  }

  condition {
    path_pattern {
      values = ["/mcp", "/mcp/*"]
    }
  }

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Security Group Rule - Allow ALB to reach AgentChat EC2
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "alb_to_chat" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  source_security_group_id = data.terraform_remote_state.portal.outputs.alb_security_group_id
  security_group_id        = module.ec2.security_group_id
  description              = "Allow ALB to reach OpenWebUI"
}

resource "aws_security_group_rule" "alb_to_mcp" {
  type                     = "ingress"
  from_port                = 3001
  to_port                  = 3001
  protocol                 = "tcp"
  source_security_group_id = data.terraform_remote_state.portal.outputs.alb_security_group_id
  security_group_id        = module.ec2.security_group_id
  description              = "Allow ALB to reach MCP server"
}

# ------------------------------------------------------------------------------
# Security Group Rule - Allow MCP Server to SSH to Kali in Range VPC
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "mcp_to_kali_ssh" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [data.terraform_remote_state.portal.outputs.vpc_cidr]
  security_group_id = data.terraform_remote_state.range.outputs.kali_security_group_id
  description       = "Allow MCP server (Portal VPC) to SSH to Kali instances"
}
