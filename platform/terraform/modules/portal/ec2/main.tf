# EC2 Module - Django portal instance
#
# Creates:
# - EC2 instance with Docker (Amazon Linux 2023)
# - Security group (app port from ALB only)
# - IAM role and instance profile (ECR pull, Secrets Manager read, SSM)
# - CloudWatch log group for container logs

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Module = "ec2"
  })
  iam_name_prefix = coalesce(var.iam_name_prefix, var.name_prefix)
  log_group_name  = "/portal/${var.name_prefix}"
  django_environment = (
    var.environment == "dev" ? "development" :
    var.environment == "prod" ? "production" :
    var.environment
  )
}

# ------------------------------------------------------------------------------
# CloudWatch Log Group for Portal Container
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "portal" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-logs"
  })
}

# Alarm on the aggregate UnhealthyWorkers metric emitted by the worker-container
# health supervisor (#953). The host agent restarts unhealthy workers and emits
# this metric every health interval; the alarm makes a persistently-unhealthy
# worker (one that keeps failing its restart) visible to operators. Shape mirrors
# the portal redis / messaging alarm convention; actions are wired from the
# per-environment SNS alerts topic via var.worker_health_alarm_actions.
resource "aws_cloudwatch_metric_alarm" "unhealthy_workers" {
  alarm_name          = "${var.name_prefix}-unhealthy-workers"
  alarm_description   = "One or more Shifter worker/scheduler containers are unhealthy and not recovering on ${var.name_prefix}"
  namespace           = "Shifter/WorkerHealth"
  metric_name         = "UnhealthyWorkers"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 2
  period              = 60
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  # Scope the alarm to this environment's metric series; the supervisor emits the
  # matching NamePrefix dimension. CloudWatch metrics are account/region scoped,
  # so without this dev and prod would share one series and cross-trip.
  dimensions = {
    NamePrefix = var.name_prefix
  }

  alarm_actions = var.worker_health_alarm_actions
  ok_actions    = var.worker_health_alarm_actions

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-unhealthy-workers"
  })
}

# Log-derived SQS worker restart signal (#274). Distinct from the #953 host
# supervisor's Shifter/WorkerHealth metrics and from Shifter/PortalCapacity.
# Per-queue series for diagnostics; a separate aggregate series feeds the alarm
# because CloudWatch alarms require a concrete metric, not SEARCH().
resource "aws_cloudwatch_log_metric_filter" "worker_restarts" {
  name           = "${var.name_prefix}-worker-restarts"
  log_group_name = aws_cloudwatch_log_group.portal.name
  pattern        = "{ ($.message = \"*Worker restart detected*\") && ($.labels.worker_queue = \"*\") }"

  metric_transformation {
    name      = "WorkerRestarts"
    namespace = "Shifter/Workers/${var.name_prefix}"
    value     = "1"

    dimensions = {
      Queue = "$.labels.worker_queue"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_restarts_aggregate" {
  name           = "${var.name_prefix}-worker-restarts-aggregate"
  log_group_name = aws_cloudwatch_log_group.portal.name
  pattern        = "{ ($.message = \"*Worker restart detected*\") && ($.labels.worker_queue = \"*\") }"

  metric_transformation {
    name          = "WorkerRestartsTotal"
    namespace     = "Shifter/Workers/${var.name_prefix}"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_restart_rate" {
  alarm_name          = "${var.name_prefix}-worker-restart-rate"
  alarm_description   = "SQS workers restarting frequently on ${var.name_prefix} (#274)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "WorkerRestartsTotal"
  namespace           = "Shifter/Workers/${var.name_prefix}"
  period              = var.worker_restart_alarm_period_seconds
  statistic           = "Sum"
  threshold           = var.worker_restart_alarm_threshold
  treat_missing_data  = "notBreaching"

  alarm_actions = var.worker_health_alarm_actions
  ok_actions    = var.worker_health_alarm_actions

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-worker-restart-rate"
  })
}

# ------------------------------------------------------------------------------
# IAM Role for EC2
# ------------------------------------------------------------------------------

resource "aws_iam_role" "this" {
  name                 = "${local.iam_name_prefix}-ec2-role"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "ecr_pull" {
  name = "ecr-pull"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*" #tfsec:ignore:aws-iam-no-policy-wildcards -- ecr:GetAuthorizationToken requires Resource=* per AWS docs
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = var.ecr_repository_arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "secrets_read" {
  name = "secrets-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = var.secret_arns
      }
    ]
  })
}

# Allow the portal EC2 role to decrypt secrets encrypted with the portal
# Secrets Manager CMK. The portal container reads values via boto3 from inside
# the container, but the underlying Secrets Manager → KMS Decrypt call runs as
# this EC2 instance role and needs kms:Decrypt on the CMK. Without it,
# `entrypoint.sh::fetch_runtime_secret` fails the GetSecretValue call with
# `AccessDeniedException: Access to KMS is not allowed`, and the existing
# bug-fix to entrypoint.sh aborts container start (better than silently
# exporting an empty env var). Scoped to the concrete CMK ARN and pinned to
# Secrets Manager via kms:ViaService. See issue #52.
resource "aws_iam_role_policy" "kms_secrets_decrypt" {
  name = "kms-secrets-decrypt"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SecretsManagerKMSAccess"
      Effect = "Allow"
      Action = [
        "kms:Decrypt",
        "kms:DescribeKey"
      ]
      Resource = var.secrets_manager_kms_key_arn
      Condition = {
        StringEquals = {
          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "cloudwatch_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.portal.arn}:*"
      }
    ]
  })
}

# IAM policy for the worker-container health supervisor (#953) to publish
# CloudWatch metrics. cloudwatch:PutMetricData has no resource-level scoping, so
# least privilege is expressed through the cloudwatch:namespace condition,
# constraining it to the Shifter/WorkerHealth namespace.
resource "aws_iam_role_policy" "cloudwatch_metrics" {
  name = "cloudwatch-metrics"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Shifter/WorkerHealth"
          }
        }
      }
    ]
  })
}

# Portal web capacity metrics (#940). The portal app process publishes
# request/terminal saturation gauges to the Shifter/PortalCapacity namespace.
# This is a SEPARATE least-privilege statement, constrained by its own
# cloudwatch:namespace condition, rather than widening the worker-health policy
# above — keeping web-capacity emission and worker-container liveness on distinct
# grants. cloudwatch:PutMetricData has no resource-level scoping, so the
# namespace condition is the boundary.
resource "aws_iam_role_policy" "cloudwatch_metrics_portal_capacity" {
  name = "cloudwatch-metrics-portal-capacity"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Shifter/PortalCapacity"
          }
        }
      }
    ]
  })
}

# IAM policy for reading range SSH keys from Secrets Manager
# SSH keys are stored at: shifter/{env}/range/{range_id}/*-ssh-key
# Required for Terminal UI feature to connect to Kali/Victim instances
resource "aws_iam_role_policy" "range_ssh_keys" {
  name = "range-ssh-keys-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:shifter/*/range/*"
      }
    ]
  })
}

# Range-events publish (#476 outbox drainer + reconciler). These workers run
# under this EC2 role and publish range status events to the range-events SNS
# topic; without sns:Publish (+ kms on the CMK-encrypted topic) the outbox never
# drains and ranges stay stuck "provisioning" in the portal forever.
resource "aws_iam_role_policy" "range_events_publish" {
  name = "range-events-publish"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RangeEventsSnsPublish"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = var.range_events_topic_arn
      },
      {
        Sid    = "RangeEventsKms"
        Effect = "Allow"
        Action = [
          "kms:GenerateDataKey*",
          "kms:Decrypt"
        ]
        Resource = var.sqs_kms_key_arn
      }
    ]
  })
}

# IAM policy for RDS IAM database authentication (#159).
# The long-running portal (web + workers) connects to the database as the
# dedicated rds_iam runtime user with a short-lived token instead of a stored
# password (config.db_backends.rds_iam; mission_control migration 0041 creates
# the user). Scoped to that single DB user on this RDS instance's resource id,
# mirroring modules/engine-provisioner/iam.tf's rds_iam_auth grant for the
# provisioner Lambda user.
resource "aws_iam_role_policy" "rds_iam_auth" {
  name = "rds-iam-auth"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "rds-db:connect"
        Resource = "arn:aws:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${var.db_resource_id}/${var.db_iam_runtime_user}"
      }
    ]
  })
}

# IAM policy for reading NGFW SSH keys from Secrets Manager
# SSH keys are stored at: shifter/{env}/ngfw/{instance_uuid}/ssh-key
# Required for NGFW CLI access feature via Guacamole SSH
resource "aws_iam_role_policy" "ngfw_ssh_keys" {
  name = "ngfw-ssh-keys-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:shifter/*/ngfw/*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "s3_access" {
  name = "s3-access"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:PutObjectTagging",
          "s3:GetObjectTagging"
        ]
        Resource = "${var.s3_bucket_arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = var.s3_bucket_arn
      }
    ]
  })
}

# Least-privilege, read-only access to the object-backed RAES package bucket
# (#1567, ADR-034-R5). The portal pulls the single immutable pack archive at
# launch and nothing else: GetObject is scoped to the optional key prefix, and
# ListBucket is constrained by an s3:prefix condition. Created only when a
# package bucket is configured, so deployments not using object-backed packs get
# no additional grant.
resource "aws_iam_role_policy" "raes_package_read" {
  count = var.raes_package_bucket_arn != "" ? 1 : 0
  name  = "raes-package-read"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${var.raes_package_bucket_arn}/${var.raes_package_prefix}*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = var.raes_package_bucket_arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["${var.raes_package_prefix}*"]
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ctf_content_read" {
  count = var.ctf_content_bucket_arn != "" ? 1 : 0
  name  = "ctf-content-read"
  role  = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${var.ctf_content_bucket_arn}/${var.ctf_content_prefix}*"
    }]
  })
}

resource "aws_iam_role_policy" "ecs_run_task" {
  name = "ecs-run-task"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RunTask"
        Effect = "Allow"
        Action = [
          "ecs:RunTask"
        ]
        # Allow all revisions of the task definition (CI/CD creates new revisions)
        Resource = "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${var.ecs_task_definition_family}:*"
      },
      {
        Sid    = "ManageTasks"
        Effect = "Allow"
        Action = [
          "ecs:DescribeTasks",
          "ecs:StopTask"
        ]
        Resource = "*" #tfsec:ignore:aws-iam-no-policy-wildcards -- scoped by Condition to specific cluster
        Condition = {
          ArnEquals = {
            "ecs:cluster" = var.ecs_cluster_arn
          }
        }
      },
      {
        Sid    = "PassRole"
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = [
          var.ecs_task_role_arn,
          var.ecs_execution_role_arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "sqs_consume" {
  name = "sqs-consume"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = var.sqs_queue_arns
      }
    ]
  })
}

resource "aws_iam_role_policy" "sqs_publish" {
  name = "sqs-publish"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage"
        ]
        Resource = var.sqs_queue_arns
      }
    ]
  })
}

resource "aws_iam_role_policy" "sqs_kms" {
  name = "sqs-kms-access"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = var.sqs_kms_key_arn
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "sqs.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "s3_kms" {
  name = "s3-kms-access"
  role = aws_iam_role.this.id

  # The portal user-storage bucket is SSE-KMS encrypted with a CMK and its
  # bucket policy *enforces* that CMK (modules/portal/s3). The CMK key policy
  # grants the account root for the s3 ViaService path, which delegates the
  # decision to IAM — so the instance role must hold kms:GenerateDataKey
  # (uploads) and kms:Decrypt (downloads) on the key or every challenge-file
  # PutObject/GetObject fails with AccessDenied / SNS-style KMS errors.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = var.s3_kms_key_arn
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "s3.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ses_send" {
  count = var.enable_ses ? 1 : 0

  name = "ses-send"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail"
        ]
        Resource = var.ses_domain_identity_arn
      },
      {
        Effect   = "Allow"
        Action   = "ses:GetSendQuota"
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# IAM policy for reading deployment config from Parameter Store
resource "aws_iam_role_policy" "ssm_parameter_read" {
  count = var.ssm_parameter_store_prefix != "" ? 1 : 0

  name = "ssm-parameter-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath"
        ]
        Resource = "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_parameter_store_prefix}/*"
      }
    ]
  })
}

# IAM policy for ASG lifecycle operations (used by user_data.sh)
resource "aws_iam_role_policy" "lifecycle_action" {
  count = var.enable_autoscaling ? 1 : 0

  name = "lifecycle-action"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "autoscaling:CompleteLifecycleAction"
        ]
        Resource = aws_autoscaling_group.this[0].arn
      },
      {
        Effect = "Allow"
        Action = [
          "autoscaling:DescribeAutoScalingInstances"
        ]
        Resource = "*" #tfsec:ignore:aws-iam-no-policy-wildcards -- Describe* actions require Resource=*
      }
    ]
  })
}

resource "aws_iam_instance_profile" "this" {
  name = "${local.iam_name_prefix}-ec2-profile"
  role = aws_iam_role.this.name

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-ec2-sg"
  description = "Security group for Django EC2 instance"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ec2-sg"
  })
}

resource "aws_security_group_rule" "app_from_alb" {
  type                     = "ingress"
  from_port                = var.app_port
  to_port                  = var.app_port
  protocol                 = "tcp"
  source_security_group_id = var.alb_security_group_id
  security_group_id        = aws_security_group.this.id
  description              = "App traffic from ALB"
}

resource "aws_security_group_rule" "egress_all" { #tfsec:ignore:aws-ec2-no-public-egress -- instance requires outbound for ECR, SES, S3, SSM, and external APIs
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"] # NOSONAR
  security_group_id = aws_security_group.this.id
  description       = "Allow all outbound (ECR, SES, S3, SSM, external APIs)"
}

# ------------------------------------------------------------------------------
# Launch Template (for ASG mode)
# ------------------------------------------------------------------------------

resource "aws_launch_template" "this" {
  count = var.enable_autoscaling ? 1 : 0

  name_prefix   = "${var.name_prefix}-lt-"
  image_id      = var.ec2_ami_id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.this.name
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.this.id]
  }

  user_data = base64gzip(templatefile("${path.module}/user_data.sh", {
    aws_region                 = var.aws_region
    django_environment         = local.django_environment
    cloud_provider             = var.cloud_provider
    ecr_repository_url         = var.ecr_repository_url
    log_group_name             = local.log_group_name
    ssm_parameter_store_prefix = var.ssm_parameter_store_prefix
    lifecycle_hook_name        = "${var.name_prefix}-launch-hook"
    name_prefix                = var.name_prefix
    docker_stop_timeout        = var.docker_stop_timeout
    worker_health_monitor_b64  = base64encode(file("${path.module}/worker-health/shifter-worker-health.sh"))
    worker_health_service_b64  = base64encode(file("${path.module}/worker-health/shifter-worker-health.service"))
    worker_health_timer_b64    = base64encode(file("${path.module}/worker-health/shifter-worker-health.timer"))
  }))

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_type           = "gp3"
      volume_size           = var.root_volume_size
      encrypted             = true
      delete_on_termination = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "enabled"
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.common_tags, {
      Name        = "${var.name_prefix}-ec2"
      ShifterRole = "shifter-platform"
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags = merge(local.common_tags, {
      Name = "${var.name_prefix}-ec2-vol"
    })
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-launch-template"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Auto Scaling Group (for ASG mode)
# ------------------------------------------------------------------------------

resource "aws_autoscaling_group" "this" {
  count = var.enable_autoscaling ? 1 : 0

  name_prefix               = "${var.name_prefix}-asg-"
  vpc_zone_identifier       = var.subnet_ids
  target_group_arns         = [var.target_group_arn]
  health_check_type         = var.health_check_type
  health_check_grace_period = var.health_check_grace_period

  # Do not block `terraform apply` on the ASG reaching capacity. New instances
  # sit in Pending:Wait until user_data finishes and calls
  # CompleteLifecycleAction (docker install + portal container boot, minutes
  # each), and warm-pool churn compounds it, so a multi-instance scale-up (e.g.
  # 2 -> 6 on a larger instance type) blows past Terraform's default 10m
  # capacity wait and fails the apply mid-roll (#1462). Readiness is gated
  # downstream by the instance refresh below plus the deploy's verify-digest /
  # verify-workers / health steps, so the in-apply wait is redundant.
  wait_for_capacity_timeout = "0"

  min_size         = var.asg_min_size
  max_size         = var.asg_max_size
  desired_capacity = var.asg_desired_capacity

  launch_template {
    id      = aws_launch_template.this[0].id
    version = "$Latest"
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = var.instance_refresh_min_healthy_percentage
      instance_warmup        = var.instance_refresh_instance_warmup
    }
  }

  dynamic "warm_pool" {
    for_each = var.asg_warm_pool_min_size > 0 ? [1] : []

    content {
      min_size   = var.asg_warm_pool_min_size
      pool_state = var.asg_warm_pool_state

      instance_reuse_policy {
        reuse_on_scale_in = true
      }
    }
  }

  dynamic "tag" {
    for_each = merge(local.common_tags, {
      Name = "${var.name_prefix}-ec2"
    })
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Auto Scaling Policies
# ------------------------------------------------------------------------------
# Portal autoscaling is driven by request-path saturation, not average EC2 CPU
# (#940). The primary scale-out/scale-in policies are ALB target-tracking
# (ALBRequestCountPerTarget + TargetResponseTime) in autoscaling_alb.tf; the
# simple policy below is an *additive* app-saturation scale-out, triggered by
# the Shifter/PortalCapacity WorkerBusyRatio alarm in observability.tf. There is
# deliberately NO CPU-low / simple scale-IN policy: leaving CPU-low as a scale-in
# path alongside target tracking lets a latency-saturated-but-low-CPU fleet scale
# in (the documented #851 / #940 failure mode), so target tracking owns the
# saturation-aware, drain-respecting scale-in. Average EC2 CPU remains only as a
# guardrail *notification* alarm (observability.tf), not a scaling action.

resource "aws_autoscaling_policy" "scale_up" {
  count = var.enable_autoscaling ? 1 : 0

  name                   = "${var.name_prefix}-app-saturation-scale-out"
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = var.scale_out_cooldown_seconds
  autoscaling_group_name = aws_autoscaling_group.this[0].name
}

# ------------------------------------------------------------------------------
# EC2 Instance (for single instance mode)
# ------------------------------------------------------------------------------

resource "aws_instance" "this" {
  count = var.enable_autoscaling ? 0 : 1

  ami                    = var.ec2_ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this.id]
  iam_instance_profile   = aws_iam_instance_profile.this.name
  monitoring             = true
  ebs_optimized          = true

  user_data_base64 = base64gzip(templatefile("${path.module}/user_data.sh", {
    aws_region                 = var.aws_region
    django_environment         = local.django_environment
    cloud_provider             = var.cloud_provider
    ecr_repository_url         = var.ecr_repository_url
    log_group_name             = local.log_group_name
    ssm_parameter_store_prefix = var.ssm_parameter_store_prefix
    lifecycle_hook_name        = ""
    name_prefix                = var.name_prefix
    docker_stop_timeout        = var.docker_stop_timeout
    worker_health_monitor_b64  = base64encode(file("${path.module}/worker-health/shifter-worker-health.sh"))
    worker_health_service_b64  = base64encode(file("${path.module}/worker-health/shifter-worker-health.service"))
    worker_health_timer_b64    = base64encode(file("${path.module}/worker-health/shifter-worker-health.timer"))
  }))

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # Enforce IMDSv2
    http_put_response_hop_limit = 2          # Allow containers to access IMDS
    instance_metadata_tags      = "enabled"
  }

  tags = merge(local.common_tags, {
    Name        = "${var.name_prefix}-ec2"
    ShifterRole = "shifter-platform"
  })

  lifecycle {
    ignore_changes = [ami]
  }
}

# ------------------------------------------------------------------------------
# ASG Lifecycle Hook (holds instance until user_data completes deployment)
# ------------------------------------------------------------------------------

resource "aws_autoscaling_lifecycle_hook" "launch" {
  count = var.enable_autoscaling ? 1 : 0

  name                   = "${var.name_prefix}-launch-hook"
  autoscaling_group_name = aws_autoscaling_group.this[0].name
  lifecycle_transition   = "autoscaling:EC2_INSTANCE_LAUNCHING"
  heartbeat_timeout      = var.lifecycle_hook_heartbeat_timeout
  default_result         = "ABANDON"
}

# ------------------------------------------------------------------------------
# ASG Termination Drain Hook (bounded drain for long-lived connections)
# ------------------------------------------------------------------------------
# Holds a terminating instance in Terminating:Wait for a bounded window so that,
# during an instance refresh or scale-in, the ALB has time to deregister the
# target (target-group deregistration_delay) and existing terminal / RDP / SSH
# WebSocket sessions can drain before the container is SIGKILLed (issue #931,
# DP-21). This is a passive timeout-only drain: no instance-side
# CompleteLifecycleAction is required, and default_result = "CONTINUE" lets the
# termination proceed automatically once heartbeat_timeout elapses, so no
# instance ever gets stuck. Kept separate from the launch hook above so launch
# bootstrap success never depends on termination-drain logic. The instance IAM
# role already scopes autoscaling:CompleteLifecycleAction to this ASG, so an
# early-completion path can be added later without an IAM change.
resource "aws_autoscaling_lifecycle_hook" "terminate" {
  count = var.enable_autoscaling ? 1 : 0

  name                   = "${var.name_prefix}-terminate-hook"
  autoscaling_group_name = aws_autoscaling_group.this[0].name
  lifecycle_transition   = "autoscaling:EC2_INSTANCE_TERMINATING"
  heartbeat_timeout      = var.termination_drain_timeout
  default_result         = "CONTINUE"
}

# Capacity-aware provisioning reads (PLAT-201, #680). The portal assesses an
# event's declared capacity against observed provider headroom before spinup.
# These grants are read-only by construction and deliberately separate from the
# provisioner's launch permissions: observing a quota must never imply the
# ability to consume it.
#
# servicequotas:GetServiceQuota and cloudwatch:GetMetricData have no
# resource-level scoping, so Resource = "*" is the API's own shape rather than a
# widened grant; the boundary is that both actions are read-only and neither can
# mutate quota or metric state.
resource "aws_iam_role_policy" "capacity_inventory_read" {
  name = "capacity-inventory-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "servicequotas:GetServiceQuota",
          "servicequotas:ListServiceQuotas",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:GetMetricData"]
        Resource = "*"
      },
    ]
  })
}

# Cross-account headroom reads (Polaris "Account B" overflow pattern). Created
# only when a deployment actually declares overflow partitions, and scoped to
# the exact role ARNs it declares -- no account wildcard, so adding an account
# to the trust path is a reviewed configuration change.
resource "aws_iam_role_policy" "capacity_inventory_assume" {
  count = length(var.capacity_inventory_read_role_arns) > 0 ? 1 : 0

  name = "capacity-inventory-assume"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sts:AssumeRole"]
        Resource = var.capacity_inventory_read_role_arns
      }
    ]
  })
}
