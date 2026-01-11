# ------------------------------------------------------------------------------
# Guacamole Module
# ------------------------------------------------------------------------------
# This module creates a highly available Apache Guacamole deployment for
# providing RDP/VNC/SSH access to range instances. It includes:
# - ECS Fargate cluster with guacd and guacamole-client services
# - Application Load Balancer for web client access
# - PostgreSQL database for authentication and connection storage
# - CloudWatch logging and monitoring
#
# Architecture:
# - guacd: The Guacamole daemon that handles protocol translation
# - guacamole-client: The web application providing HTML5 interface
# - Both run as ECS Fargate services for high availability
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ------------------------------------------------------------------------------
# Local Variables
# ------------------------------------------------------------------------------

locals {
  common_tags = merge(var.tags, {
    Module = "guacamole"
  })
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.id
}

# ------------------------------------------------------------------------------
# ECS Cluster
# ------------------------------------------------------------------------------

resource "aws_ecs_cluster" "guacamole" {
  name = "${var.name_prefix}-guacamole"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole"
  })
}

resource "aws_ecs_cluster_capacity_providers" "guacamole" {
  cluster_name       = aws_ecs_cluster.guacamole.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ------------------------------------------------------------------------------
# CloudWatch Log Groups
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "guacd" {
  name              = "/ecs/${var.name_prefix}-guacd"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacd-logs"
  })
}

resource "aws_cloudwatch_log_group" "guacamole_client" {
  name              = "/ecs/${var.name_prefix}-guacamole-client"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-client-logs"
  })
}

# ------------------------------------------------------------------------------
# Service Discovery Namespace (for guacd internal communication)
# ------------------------------------------------------------------------------

resource "aws_service_discovery_private_dns_namespace" "guacamole" {
  name        = "guacamole.${var.environment}.internal"
  description = "Service discovery namespace for Guacamole services"
  vpc         = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-namespace"
  })
}

resource "aws_service_discovery_service" "guacd" {
  name = "guacd"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.guacamole.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  # failure_threshold is deprecated - AWS always uses 1 regardless of config
  # Must set to 1 to match AWS state and prevent drift
  # See: https://github.com/hashicorp/terraform-provider-aws/issues/35559
  health_check_custom_config {
    failure_threshold = 1
  }

  tags = local.common_tags
}
