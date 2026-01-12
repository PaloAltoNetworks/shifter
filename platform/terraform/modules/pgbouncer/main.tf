# ------------------------------------------------------------------------------
# PgBouncer Module
# ------------------------------------------------------------------------------
# Creates:
# - ECS Cluster for PgBouncer
# - ECS Task Definition and Service
# - Service Discovery for DNS-based load balancing
# - CloudWatch Log Group
# - Security Groups
# - IAM Roles

locals {
  common_tags = merge(var.tags, {
    Module = "pgbouncer"
  })

  # Extract host and port from RDS endpoint (format: hostname:port)
  rds_host = split(":", var.rds_endpoint)[0]
  rds_port = split(":", var.rds_endpoint)[1]
}

# Get current AWS region
data "aws_region" "current" {}

# ------------------------------------------------------------------------------
# ECS Cluster
# ------------------------------------------------------------------------------

resource "aws_ecs_cluster" "pgbouncer" {
  name = "${var.name_prefix}-pgbouncer"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer"
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Log Group
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "pgbouncer" {
  name              = "/ecs/${var.name_prefix}-pgbouncer"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer-logs"
  })
}

# ------------------------------------------------------------------------------
# Service Discovery
# ------------------------------------------------------------------------------

resource "aws_service_discovery_private_dns_namespace" "pgbouncer" {
  name        = "pgbouncer.${var.environment}.internal"
  description = "Service discovery namespace for PgBouncer"
  vpc         = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer-namespace"
  })
}

resource "aws_service_discovery_service" "pgbouncer" {
  name = "portal-db"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.pgbouncer.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer-service"
  })
}

# ------------------------------------------------------------------------------
# ECS Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "pgbouncer" {
  family                   = "${var.name_prefix}-pgbouncer"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "pgbouncer"
    image     = var.pgbouncer_image
    essential = true

    portMappings = [{
      containerPort = 5432
      protocol      = "tcp"
    }]

    # Environment variables for pgbouncer configuration
    # The edoburu/pgbouncer image uses DATABASE_URL format
    environment = [
      { name = "POOL_MODE", value = var.pool_mode },
      { name = "MAX_CLIENT_CONN", value = tostring(var.max_client_conn) },
      { name = "DEFAULT_POOL_SIZE", value = tostring(var.default_pool_size) },
      { name = "MIN_POOL_SIZE", value = tostring(var.min_pool_size) },
      { name = "RESERVE_POOL_SIZE", value = tostring(var.reserve_pool_size) },
      { name = "SERVER_LIFETIME", value = "3600" },
      { name = "SERVER_IDLE_TIMEOUT", value = "600" },
      { name = "DB_HOST", value = local.rds_host },
      { name = "DB_PORT", value = local.rds_port },
      { name = "DB_NAME", value = var.db_name },
    ]

    # Secrets from Secrets Manager
    secrets = [
      {
        name      = "DB_USER"
        valueFrom = "${var.db_credentials_secret_arn}:username::"
      },
      {
        name      = "DB_PASSWORD"
        valueFrom = "${var.db_credentials_secret_arn}:password::"
      }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.pgbouncer.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "pgbouncer"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "pg_isready -h localhost -p 5432 || exit 1"]
      interval    = 10
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
  }])

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer"
  })
}

# ------------------------------------------------------------------------------
# ECS Service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "pgbouncer" {
  name            = "${var.name_prefix}-pgbouncer"
  cluster         = aws_ecs_cluster.pgbouncer.id
  task_definition = aws_ecs_task_definition.pgbouncer.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.pgbouncer.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.pgbouncer.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pgbouncer"
  })

  lifecycle {
    ignore_changes = [desired_count]
  }
}
