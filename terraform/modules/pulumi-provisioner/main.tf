# ------------------------------------------------------------------------------
# Pulumi Provisioner Module
# ------------------------------------------------------------------------------
# This module creates ECS Fargate infrastructure for running Pulumi-based
# range provisioning tasks. It includes:
# - ECS cluster with Fargate capacity provider
# - CloudWatch log groups for ECS and Step Functions
# - Task definitions (see task_definition.tf)
# - IAM roles (see iam.tf)
# - Security groups (see security.tf)
# - Step Functions state machines (see step_functions.tf)
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
    Module = "pulumi-provisioner"
  })
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.id
}

# ------------------------------------------------------------------------------
# ECS Cluster
# ------------------------------------------------------------------------------

resource "aws_ecs_cluster" "pulumi" {
  name = "${var.name_prefix}-pulumi"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi"
  })
}

resource "aws_ecs_cluster_capacity_providers" "pulumi" {
  cluster_name       = aws_ecs_cluster.pulumi.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }
}

# ------------------------------------------------------------------------------
# CloudWatch Log Groups
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.name_prefix}-pulumi-provisioner"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-provisioner-logs"
  })
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/stepfunctions/${var.name_prefix}-pulumi-provisioner"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-provisioner-sfn-logs"
  })
}
