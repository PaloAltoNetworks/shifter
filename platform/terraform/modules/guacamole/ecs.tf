# ------------------------------------------------------------------------------
# ECS Task Definitions and Services
# ------------------------------------------------------------------------------
# Creates:
# - guacd task definition and service (protocol translation daemon)
# - guacamole-client task definition and service (web application)
# - Auto scaling for both services

# ------------------------------------------------------------------------------
# Local Variables for Container Configuration
# ------------------------------------------------------------------------------

locals {
  # Base environment variables for guacamole-client
  guacamole_base_env = [
    # Guacd connection via service discovery
    { name = "GUACD_HOSTNAME", value = "guacd.guacamole.${var.environment}.internal" },
    { name = "GUACD_PORT", value = "4822" },

    # PostgreSQL connection
    { name = "POSTGRESQL_HOSTNAME", value = aws_db_instance.guacamole.address },
    { name = "POSTGRESQL_PORT", value = tostring(aws_db_instance.guacamole.port) },
    { name = "POSTGRESQL_DATABASE", value = "guacamole" },

    # Auto-create schema and default admin on first startup
    { name = "POSTGRESQL_AUTO_CREATE_ACCOUNTS", value = "true" },
  ]

  # OIDC environment variables (only when enabled)
  # Uses local values computed in cognito.tf from the Cognito app client
  guacamole_oidc_env = var.enable_oidc ? [
    { name = "OPENID_AUTHORIZATION_ENDPOINT", value = local.oidc_authorization_endpoint },
    { name = "OPENID_JWKS_ENDPOINT", value = local.oidc_jwks_endpoint },
    { name = "OPENID_ISSUER", value = local.oidc_issuer_url },
    { name = "OPENID_CLIENT_ID", value = local.oidc_client_id },
    { name = "OPENID_REDIRECT_URI", value = local.oidc_redirect_uri },
    { name = "OPENID_SCOPE", value = "openid email profile" },
    { name = "OPENID_USERNAME_CLAIM_TYPE", value = "email" },
  ] : []

  # Combined environment variables
  guacamole_environment = concat(local.guacamole_base_env, local.guacamole_oidc_env)
}

# ------------------------------------------------------------------------------
# Guacd Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "guacd" {
  family                   = "${var.name_prefix}-guacd"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.guacd_cpu
  memory                   = var.guacd_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.guacd_task.arn

  container_definitions = jsonencode([{
    name      = "guacd"
    image     = "${var.guacd_ecr_repository_url}:${var.guacd_image_tag}"
    essential = true

    portMappings = [{
      containerPort = 4822
      protocol      = "tcp"
    }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.guacd.name
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "guacd"
      }
    }

    # Health check removed - official guacd image lacks netcat
    # See GitHub issue for investigation of alternative health check
  }])

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacd"
  })
}

# ------------------------------------------------------------------------------
# Guacd ECS Service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "guacd" {
  name            = "${var.name_prefix}-guacd"
  cluster         = aws_ecs_cluster.guacamole.id
  task_definition = aws_ecs_task_definition.guacd.arn
  desired_count   = var.guacd_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.guacd.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.guacd.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacd"
  })

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ------------------------------------------------------------------------------
# Guacamole Client Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "guacamole_client" {
  family                   = "${var.name_prefix}-guacamole-client"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.guacamole_client_cpu
  memory                   = var.guacamole_client_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.guacamole_client_task.arn

  container_definitions = jsonencode([{
    name      = "guacamole-client"
    image     = "${var.guacamole_client_ecr_repository_url}:${var.guacamole_client_image_tag}"
    essential = true

    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]

    environment = local.guacamole_environment

    secrets = [
      {
        name      = "POSTGRESQL_USER"
        valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:username::"
      },
      {
        name      = "POSTGRESQL_PASSWORD"
        valueFrom = "${aws_secretsmanager_secret.db_credentials.arn}:password::"
      }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.guacamole_client.name
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "guacamole"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/guacamole/ || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 120
    }
  }])

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-client"
  })
}

# ------------------------------------------------------------------------------
# Guacamole Client ECS Service
# ------------------------------------------------------------------------------

resource "aws_ecs_service" "guacamole_client" {
  name            = "${var.name_prefix}-guacamole-client"
  cluster         = aws_ecs_cluster.guacamole.id
  task_definition = aws_ecs_task_definition.guacamole_client.arn
  desired_count   = var.guacamole_client_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.guacamole_client.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.guacamole.arn
    container_name   = "guacamole-client"
    container_port   = 8080
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-client"
  })

  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [
    aws_lb_listener_rule.guacamole,
    aws_ecs_service.guacd
  ]
}

# ------------------------------------------------------------------------------
# Auto Scaling - Guacd
# ------------------------------------------------------------------------------

resource "aws_appautoscaling_target" "guacd" {
  count = var.enable_autoscaling ? 1 : 0

  max_capacity       = var.autoscaling_max_capacity
  min_capacity       = var.autoscaling_min_capacity
  resource_id        = "service/${aws_ecs_cluster.guacamole.name}/${aws_ecs_service.guacd.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "guacd_cpu" {
  count = var.enable_autoscaling ? 1 : 0

  name               = "${var.name_prefix}-guacd-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.guacd[0].resource_id
  scalable_dimension = aws_appautoscaling_target.guacd[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.guacd[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.autoscaling_cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# ------------------------------------------------------------------------------
# Auto Scaling - Guacamole Client
# ------------------------------------------------------------------------------

resource "aws_appautoscaling_target" "guacamole_client" {
  count = var.enable_autoscaling ? 1 : 0

  max_capacity       = var.autoscaling_max_capacity
  min_capacity       = var.autoscaling_min_capacity
  resource_id        = "service/${aws_ecs_cluster.guacamole.name}/${aws_ecs_service.guacamole_client.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "guacamole_client_cpu" {
  count = var.enable_autoscaling ? 1 : 0

  name               = "${var.name_prefix}-guacamole-client-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.guacamole_client[0].resource_id
  scalable_dimension = aws_appautoscaling_target.guacamole_client[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.guacamole_client[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = var.autoscaling_cpu_target
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
