# OpenBAS Shared Infrastructure Module
#
# Provides centralized adversary emulation platform for all ranges.
# Deploys as shared infrastructure in the Range VPC.
#
# Components:
# - ECS Fargate service (HA across AZs)
# - RDS PostgreSQL database
# - Target group for Portal ALB routing (/shifter-mirage/bas/*)
# - Security groups and IAM roles
#
# Traffic flow:
# - Portal ALB -> VPC Peering -> ECS tasks (port 8080)
# - Route: /shifter-mirage/bas/* -> OpenBAS target group

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

# ------------------------------------------------------------------------------
# Local Variables
# ------------------------------------------------------------------------------

locals {
  common_tags = merge(var.tags, {
    Module = "openbas"
  })
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  # Use first two AZs for HA deployment
  az_count = min(2, length(data.aws_availability_zones.available.names))
  azs      = slice(data.aws_availability_zones.available.names, 0, local.az_count)
}

# ------------------------------------------------------------------------------
# ECS Cluster
# ------------------------------------------------------------------------------

resource "aws_ecs_cluster" "openbas" {
  name = "${var.name_prefix}-openbas"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas"
  })
}

resource "aws_ecs_cluster_capacity_providers" "openbas" {
  cluster_name       = aws_ecs_cluster.openbas.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ------------------------------------------------------------------------------
# CloudWatch Log Groups
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "openbas" {
  name              = "/ecs/${var.name_prefix}-openbas"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-logs"
  })
}

# ------------------------------------------------------------------------------
# ECS Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "openbas" {
  family                   = "${var.name_prefix}-openbas"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "openbas"
      image     = var.openbas_image
      essential = true

      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "OPENBAS_BASE_URL"
          value = var.base_url
        },
        {
          name  = "OPENBAS_AUTH_LOCAL_ENABLE"
          value = "true"
        },
        {
          name  = "SPRING_DATASOURCE_URL"
          value = "jdbc:postgresql://${aws_db_instance.openbas.endpoint}/${var.db_name}"
        },
        {
          name  = "SPRING_DATASOURCE_USERNAME"
          value = var.db_username
        },
        {
          name  = "MINIO_ENDPOINT"
          value = "s3.${local.region}.amazonaws.com"
        },
        {
          name  = "MINIO_BUCKET"
          value = aws_s3_bucket.openbas.id
        },
        {
          name  = "MINIO_USE_AWS_ROLE"
          value = "true"
        }
      ]

      secrets = [
        {
          name      = "SPRING_DATASOURCE_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:password::"
        },
        {
          name      = "OPENBAS_ADMIN_TOKEN"
          valueFrom = "${aws_secretsmanager_secret.admin_token.arn}:token::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.openbas.name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "openbas"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/api/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 120
      }
    }
  ])

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# ECS Service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "openbas" {
  name                               = "${var.name_prefix}-openbas"
  cluster                            = aws_ecs_cluster.openbas.id
  task_definition                    = aws_ecs_task_definition.openbas.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 180
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = aws_subnet.openbas[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.openbas.arn
    container_name   = "openbas"
    container_port   = 8080
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = local.common_tags

  depends_on = [
    aws_db_instance.openbas,
  ]

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ------------------------------------------------------------------------------
# Auto Scaling
# ------------------------------------------------------------------------------

resource "aws_appautoscaling_target" "openbas" {
  count = var.enable_autoscaling ? 1 : 0

  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${aws_ecs_cluster.openbas.name}/${aws_ecs_service.openbas.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "openbas_cpu" {
  count = var.enable_autoscaling ? 1 : 0

  name               = "${var.name_prefix}-openbas-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.openbas[0].resource_id
  scalable_dimension = aws_appautoscaling_target.openbas[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.openbas[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "openbas_memory" {
  count = var.enable_autoscaling ? 1 : 0

  name               = "${var.name_prefix}-openbas-memory"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.openbas[0].resource_id
  scalable_dimension = aws_appautoscaling_target.openbas[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.openbas[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 80
    scale_in_cooldown  = 300
    scale_out_cooldown = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
  }
}
