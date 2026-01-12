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

    # Environment variables for bitnami/pgbouncer
    # https://github.com/bitnami/containers/tree/main/bitnami/pgbouncer
    environment = [
      # Backend PostgreSQL connection
      { name = "POSTGRESQL_HOST", value = local.rds_host },
      { name = "POSTGRESQL_PORT", value = local.rds_port },
      { name = "POSTGRESQL_DATABASE", value = var.db_name },
      # PgBouncer pool settings
      { name = "PGBOUNCER_POOL_MODE", value = var.pool_mode },
      { name = "PGBOUNCER_MAX_CLIENT_CONN", value = tostring(var.max_client_conn) },
      { name = "PGBOUNCER_DEFAULT_POOL_SIZE", value = tostring(var.default_pool_size) },
      { name = "PGBOUNCER_MIN_POOL_SIZE", value = tostring(var.min_pool_size) },
      { name = "PGBOUNCER_RESERVE_POOL_SIZE", value = tostring(var.reserve_pool_size) },
      { name = "PGBOUNCER_SERVER_LIFETIME", value = "3600" },
      { name = "PGBOUNCER_SERVER_IDLE_TIMEOUT", value = "600" },
      # Auth configuration for SCRAM-SHA-256 (PostgreSQL 16 default)
      { name = "PGBOUNCER_AUTH_TYPE", value = "scram-sha-256" },
      { name = "PGBOUNCER_AUTH_QUERY", value = "SELECT username, password FROM pgbouncer.get_auth($1)" },
      # Ignore startup parameters that pgbouncer doesn't support
      { name = "PGBOUNCER_IGNORE_STARTUP_PARAMETERS", value = "extra_float_digits,options" },
    ]

    # Secrets from Secrets Manager
    secrets = [
      # Backend database credentials (for server connections)
      {
        name      = "POSTGRESQL_USERNAME"
        valueFrom = "${var.db_credentials_secret_arn}:username::"
      },
      {
        name      = "POSTGRESQL_PASSWORD"
        valueFrom = "${var.db_credentials_secret_arn}:password::"
      },
      # Auth user credentials (for auth_query lookups)
      {
        name      = "PGBOUNCER_AUTH_USER"
        valueFrom = "${var.auth_user_secret_arn}:username::"
      },
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
