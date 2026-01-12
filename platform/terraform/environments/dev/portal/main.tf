terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.environment}-portal"
  # Add padding to field_encryption_key (b64_url doesn't include padding, but Fernet requires it)
  field_encryption_key_padded = "${random_id.field_encryption_key.b64_url}="
}

# ------------------------------------------------------------------------------
# Remote State - Foundation (ECR)
# ------------------------------------------------------------------------------

data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "shifter/dev/terraform.tfstate"
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
# AMI IDs from SSM Parameter Store
# ------------------------------------------------------------------------------

data "aws_ssm_parameter" "kali_ami" {
  name = "/shifter/ami/kali"
}

data "aws_ssm_parameter" "victim_ami" {
  name = "/shifter/ami/ubuntu"
}

data "aws_ssm_parameter" "windows_ami" {
  name = "/shifter/ami/windows"
}

data "aws_ssm_parameter" "dc_ami" {
  name = "/shifter/ami/dc"
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/portal/vpc"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  az_count           = var.az_count
  enable_nat_gateway = var.enable_nat_gateway
  tags               = var.tags

  # Phase 5: VPC Flow Logs
  enable_flow_logs   = var.enable_vpc_flow_logs
  log_retention_days = var.log_retention_days
}

# ------------------------------------------------------------------------------
# RDS PostgreSQL
# ------------------------------------------------------------------------------

module "rds" {
  source = "../../../modules/portal/rds"

  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [module.vpc.vpc_cidr]

  db_name               = var.db_name
  db_username           = var.db_username
  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.db_deletion_protection
  skip_final_snapshot   = var.db_skip_final_snapshot

  # Phase 5: RDS Log Exports
  enable_log_exports = var.enable_rds_log_exports
  log_retention_days = var.log_retention_days

  tags = var.tags
}

# ------------------------------------------------------------------------------
# PgBouncer Auth User Credentials
# ------------------------------------------------------------------------------
# The password is generated here and stored in Secrets Manager.
# The actual PostgreSQL user is created via SSM command to portal EC2 (see below).
# This approach works because portal EC2 has VPC access to RDS while GitHub runner cannot.

resource "random_password" "pgbouncer_auth_password" {
  length  = 32
  special = false # Avoid special chars for connection string compatibility
}

# checkov:skip=CKV_AWS_149:AWS-managed keys sufficient for internal MVP
resource "aws_secretsmanager_secret" "pgbouncer_auth" {
  name                    = "shifter-${local.name_prefix}-pgbouncer-auth"
  description             = "PgBouncer auth user credentials for auth_query"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "shifter-${local.name_prefix}-pgbouncer-auth"
  })
}

resource "aws_secretsmanager_secret_version" "pgbouncer_auth" {
  secret_id = aws_secretsmanager_secret.pgbouncer_auth.id
  secret_string = jsonencode({
    username = "pgbouncer_auth"
    password = random_password.pgbouncer_auth_password.result
  })
}

# ------------------------------------------------------------------------------
# ALB (created first, target attached after EC2)
# ------------------------------------------------------------------------------

module "alb" {
  source = "../../../modules/portal/alb"

  name_prefix       = local.name_prefix
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  domain_name       = var.domain_name
  app_port          = var.app_port
  health_check_path = var.health_check_path
  enable_stickiness = var.enable_autoscaling

  # Phase 5: ALB Access Logs and WAF Logging
  enable_access_logs      = var.enable_alb_access_logs
  logs_bucket_name        = var.enable_alb_access_logs ? module.log_aggregation.logs_bucket_name : ""
  enable_waf_logging      = var.enable_waf_logging
  waf_log_destination_arn = var.enable_waf_logging ? module.log_aggregation.waf_firehose_arn : ""

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Redis (for Django Channels in ASG mode)
# ------------------------------------------------------------------------------

module "redis" {
  source = "../../../modules/portal/redis"

  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [module.vpc.vpc_cidr]
  node_type           = var.redis_node_type
  engine_version      = var.redis_engine_version
  enable_replication  = var.redis_enable_replication

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

module "cognito" {
  source = "../../../modules/portal/cognito"

  name_prefix           = local.name_prefix
  environment           = var.environment
  aws_region            = var.aws_region
  log_retention_days    = var.log_retention_days
  cognito_domain_prefix = var.cognito_domain_prefix
  callback_urls         = ["https://${var.domain_name}/oidc/callback/"]
  logout_urls           = ["https://${var.domain_name}/"]
  allowed_email_domains = var.allowed_email_domains
  allowed_emails        = var.allowed_emails
  deletion_protection   = false

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Shared Alerting SNS Topic
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count = var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ------------------------------------------------------------------------------
# Messaging (SNS/SQS)
# ------------------------------------------------------------------------------

module "messaging" {
  source = "../../../modules/portal/messaging"

  name_prefix                = local.name_prefix
  tags                       = var.tags
  consumers                  = var.messaging_consumers
  visibility_timeout_seconds = var.messaging_visibility_timeout_seconds
  message_retention_seconds  = var.messaging_message_retention_seconds

  # Dead Letter Queue
  enable_dlq                    = var.messaging_enable_dlq
  dlq_max_receive_count         = var.messaging_dlq_max_receive_count
  dlq_message_retention_seconds = var.messaging_dlq_message_retention_seconds

  # CloudWatch Alarms
  enable_alarms               = var.messaging_enable_alarms
  alarm_queue_depth_threshold = var.messaging_alarm_queue_depth_threshold
  alarm_message_age_threshold = var.messaging_alarm_message_age_threshold
  alarm_dlq_threshold         = var.messaging_alarm_dlq_threshold
  alarm_actions               = var.alarm_email != "" ? [aws_sns_topic.alerts.arn] : []
}

# ------------------------------------------------------------------------------
# SSM Deployment (Parameter Store + SSM Document)
# ------------------------------------------------------------------------------

module "ssm" {
  source = "../../../modules/portal/ssm"

  environment = var.environment
  name_prefix = local.name_prefix
  aws_region  = var.aws_region
  tags        = var.tags

  # ECR configuration
  ecr_registry        = split("/", data.terraform_remote_state.foundation.outputs.portal_ecr_url)[0]
  ecr_repository_name = split("/", data.terraform_remote_state.foundation.outputs.portal_ecr_url)[1]

  # Secrets Manager ARNs
  db_secret_arn          = module.rds.db_credentials_secret_arn
  app_secret_arn         = aws_secretsmanager_secret.app.arn
  cognito_secret_arn     = module.cognito.cognito_secret_arn
  guacamole_secret_arn   = module.guacamole.json_auth_secret_arn
  guacamole_base_url     = "https://${var.domain_name}/guacamole"
  guacamole_api_base_url = module.guacamole.guacamole_client_internal_url

  # Application configuration
  domain_name    = var.domain_name
  s3_bucket_name = var.user_storage_bucket

  # Pulumi provisioner configuration
  pulumi_ecs_cluster_arn       = module.pulumi_provisioner.ecs_cluster_arn
  pulumi_task_definition_arn   = module.pulumi_provisioner.task_definition_arn
  pulumi_ecs_security_group_id = module.pulumi_provisioner.ecs_security_group_id
  pulumi_private_subnet_ids    = join(",", module.vpc.private_subnet_ids)

  # Messaging configuration
  sqs_cms_url    = module.messaging.sqs_queue_urls["cms"]
  sqs_engine_url = module.messaging.sqs_queue_urls["engine"]
  sqs_mc_url     = module.messaging.sqs_queue_urls["mc"]
  redis_endpoint = var.enable_autoscaling ? module.redis.redis_endpoint : ""

  # PgBouncer endpoint (for connection pooling)
  db_host_override = module.pgbouncer.service_discovery_endpoint

  # Logging level (DEBUG for dev, INFO for prod)
  log_level = var.log_level
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

module "ec2" {
  source = "../../../modules/portal/ec2"

  aws_region            = var.aws_region
  ec2_ami_id            = var.ec2_ami_id
  name_prefix           = local.name_prefix
  vpc_id                = module.vpc.vpc_id
  subnet_id             = module.vpc.private_subnet_ids[0]
  alb_security_group_id = module.alb.security_group_id
  instance_type         = var.ec2_instance_type
  ecr_repository_arn    = data.terraform_remote_state.foundation.outputs.portal_ecr_arn
  ecr_repository_url    = data.terraform_remote_state.foundation.outputs.portal_ecr_url
  secret_arns = [
    module.rds.db_credentials_secret_arn,
    aws_secretsmanager_secret.app.arn,
    module.cognito.cognito_secret_arn,
    module.guacamole.json_auth_secret_arn,
    aws_secretsmanager_secret.pgbouncer_auth.arn,
  ]
  s3_bucket_arn    = module.s3.bucket_arn
  app_port         = var.app_port
  root_volume_size = var.ec2_root_volume_size

  # ECS permissions for Pulumi provisioner
  ecs_cluster_arn            = module.pulumi_provisioner.ecs_cluster_arn
  ecs_task_definition_family = module.pulumi_provisioner.task_definition_family
  ecs_task_role_arn          = module.pulumi_provisioner.ecs_task_role_arn
  ecs_execution_role_arn     = module.pulumi_provisioner.ecs_execution_role_arn

  # Autoscaling configuration
  enable_autoscaling   = var.enable_autoscaling
  subnet_ids           = module.vpc.private_subnet_ids
  target_group_arn     = module.alb.target_group_arn
  asg_min_size         = var.asg_min_size
  asg_max_size         = var.asg_max_size
  asg_desired_capacity = var.asg_desired_capacity
  redis_endpoint       = var.enable_autoscaling ? module.redis.redis_endpoint : ""
  scale_up_threshold   = var.scale_up_threshold
  scale_down_threshold = var.scale_down_threshold
  log_retention_days   = var.log_retention_days

  # Messaging (SQS queues for message consumers)
  sqs_queue_arns = values(module.messaging.sqs_queue_arns)
  sqs_queue_urls = module.messaging.sqs_queue_urls

  # Parameter Store prefix for user_data bootstrap
  ssm_parameter_store_prefix = module.ssm.parameter_store_prefix

  tags = var.tags
}

# ------------------------------------------------------------------------------
# ALB Target Attachment (single instance mode only - ASG attaches automatically)
# ------------------------------------------------------------------------------

resource "aws_lb_target_group_attachment" "portal" {
  count = var.enable_autoscaling ? 0 : 1

  target_group_arn = module.alb.target_group_arn
  target_id        = module.ec2.instance_id
  port             = var.app_port
}

# ------------------------------------------------------------------------------
# S3 User Storage
# ------------------------------------------------------------------------------

module "s3" {
  source = "../../../modules/portal/s3"

  bucket_name          = var.user_storage_bucket
  cors_allowed_origins = ["https://${var.domain_name}"]
  tags                 = var.tags
}

# ------------------------------------------------------------------------------
# App Secret (Django secret key)
# ------------------------------------------------------------------------------

resource "random_password" "django_secret_key" {
  length  = 50
  special = true
}

# Fernet encryption key for django-encrypted-model-fields (32 bytes, base64-encoded)
resource "random_id" "field_encryption_key" {
  byte_length = 32
}

# checkov:skip=CKV_AWS_149:Deferred for MVP. AWS-managed keys sufficient for low-usage internal MVP. See #213
resource "aws_secretsmanager_secret" "app" {
  name                    = "shifter-${local.name_prefix}-app"
  description             = "Django application secrets"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "shifter-${local.name_prefix}-app"
  })
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    django_secret_key    = random_password.django_secret_key.result
    field_encryption_key = local.field_encryption_key_padded
  })
}

# ------------------------------------------------------------------------------
# VPC Peering: Portal <-> Range
# Enables SSH connectivity from Portal to Range instances for Terminal UI
# ------------------------------------------------------------------------------

resource "aws_vpc_peering_connection" "portal_to_range" {
  vpc_id      = module.vpc.vpc_id
  peer_vpc_id = data.terraform_remote_state.range.outputs.vpc_id
  auto_accept = true # Same account, same region

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-to-range-peering"
  })
}

# Route from Portal private subnets to Range VPC via peering
resource "aws_route" "portal_to_range" {
  route_table_id            = module.vpc.private_route_table_id
  destination_cidr_block    = data.terraform_remote_state.range.outputs.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Route from Range private subnets to Portal VPC via peering
resource "aws_route" "range_to_portal" {
  route_table_id            = data.terraform_remote_state.range.outputs.private_route_table_id
  destination_cidr_block    = module.vpc.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Note: SSH rules from Portal to Kali/Victim are defined in the range VPC module
# (terraform/modules/range/vpc/main.tf) using the portal_vpc_cidr variable.
# Do not duplicate them here.

# ------------------------------------------------------------------------------
# Pulumi Provisioner (ECS Fargate)
# Note: Defined before log_aggregation so its log groups can be included
# ------------------------------------------------------------------------------

module "pulumi_provisioner" {
  source = "../../../modules/pulumi-provisioner"

  name_prefix        = local.name_prefix
  environment        = var.environment
  tags               = var.tags
  log_retention_days = var.log_retention_days

  # ECR
  ecr_repository_url  = data.terraform_remote_state.foundation.outputs.pulumi_provisioner_ecr_url
  container_image_tag = var.pulumi_container_tag

  # Networking (Portal VPC for RDS access)
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  # Database (via PgBouncer for connection pooling)
  db_host        = module.pgbouncer.service_discovery_endpoint
  db_port        = 5432
  db_name        = var.db_name
  db_resource_id = module.rds.db_resource_id

  # PgBouncer security group (for adding ingress rule)
  rds_security_group_id = module.pgbouncer.security_group_id

  # Pulumi state (from Range environment)
  pulumi_state_bucket          = data.terraform_remote_state.range.outputs.pulumi_state_bucket_name
  pulumi_state_bucket_arn      = data.terraform_remote_state.range.outputs.pulumi_state_bucket_arn
  pulumi_locks_table           = data.terraform_remote_state.range.outputs.pulumi_locks_table_name
  pulumi_locks_table_arn       = data.terraform_remote_state.range.outputs.pulumi_locks_table_arn
  pulumi_secrets_kms_key_arn   = data.terraform_remote_state.range.outputs.pulumi_secrets_kms_key_arn
  pulumi_secrets_kms_key_alias = data.terraform_remote_state.range.outputs.pulumi_secrets_kms_key_alias

  # Range VPC configuration
  range_vpc_id                = data.terraform_remote_state.range.outputs.vpc_id
  range_vpc_cidr              = data.terraform_remote_state.range.outputs.vpc_cidr
  range_route_table_id        = data.terraform_remote_state.range.outputs.private_route_table_id
  range_availability_zone     = data.terraform_remote_state.range.outputs.availability_zone
  victim_security_group_id    = data.terraform_remote_state.range.outputs.victim_security_group_id
  kali_security_group_id      = data.terraform_remote_state.range.outputs.kali_security_group_id
  dc_security_group_id        = data.terraform_remote_state.range.outputs.dc_security_group_id
  range_instance_profile_arn  = data.terraform_remote_state.range.outputs.range_instance_profile_arn
  range_instance_profile_name = data.terraform_remote_state.range.outputs.range_instance_profile_name
  range_instance_role_arn     = data.terraform_remote_state.range.outputs.range_instance_role_arn

  # AMIs (from SSM Parameter Store)
  kali_ami_id    = data.aws_ssm_parameter.kali_ami.value
  victim_ami_id  = data.aws_ssm_parameter.victim_ami.value
  windows_ami_id = data.aws_ssm_parameter.windows_ami.value
  dc_ami_id      = data.aws_ssm_parameter.dc_ami.value

  # Prebaked DC configuration
  dc_domain_name     = var.dc_domain_name
  dc_domain_password = var.dc_domain_password

  # Instance types
  kali_instance_type   = var.kali_instance_type
  victim_instance_type = var.victim_instance_type

  # S3
  agent_s3_bucket     = module.s3.bucket_name
  agent_s3_bucket_arn = module.s3.bucket_arn

  # NGFW (VM-Series) - from Range VPC outputs
  ngfw_mgmt_security_group_id = data.terraform_remote_state.range.outputs.ngfw_mgmt_security_group_id != null ? data.terraform_remote_state.range.outputs.ngfw_mgmt_security_group_id : ""
  ngfw_data_security_group_id = data.terraform_remote_state.range.outputs.ngfw_data_security_group_id != null ? data.terraform_remote_state.range.outputs.ngfw_data_security_group_id : ""
  ngfw_ami_id                 = data.terraform_remote_state.range.outputs.vm_series_ami_id
  ngfw_instance_type          = data.terraform_remote_state.range.outputs.vm_series_instance_type
  ngfw_subnet_id              = data.terraform_remote_state.range.outputs.ngfw_subnet_id != null ? data.terraform_remote_state.range.outputs.ngfw_subnet_id : ""
  ngfw_instance_profile_name  = data.terraform_remote_state.range.outputs.ngfw_instance_profile_name != null ? data.terraform_remote_state.range.outputs.ngfw_instance_profile_name : ""

  # Messaging (SNS topic for range event publishing)
  sns_topic_arn = module.messaging.sns_topic_arn
}

# ------------------------------------------------------------------------------
# Guacamole (Remote Desktop Gateway)
# ------------------------------------------------------------------------------

module "guacamole" {
  source = "../../../modules/guacamole"

  name_prefix = local.name_prefix
  environment = var.environment
  tags        = var.tags

  # Networking (Portal VPC)
  vpc_id                   = module.vpc.vpc_id
  private_subnet_ids       = module.vpc.private_subnet_ids
  range_vpc_cidr           = data.terraform_remote_state.range.outputs.vpc_cidr
  portal_security_group_id = module.ec2.security_group_id

  # Shared ALB (from Portal ALB module)
  alb_listener_arn      = module.alb.https_listener_arn
  alb_security_group_id = module.alb.security_group_id

  # ECR (from foundation remote state)
  guacd_ecr_repository_url            = data.terraform_remote_state.foundation.outputs.guacd_ecr_url
  guacd_ecr_repository_arn            = data.terraform_remote_state.foundation.outputs.guacd_ecr_arn
  guacamole_client_ecr_repository_url = data.terraform_remote_state.foundation.outputs.guacamole_client_ecr_url
  guacamole_client_ecr_repository_arn = data.terraform_remote_state.foundation.outputs.guacamole_client_ecr_arn

  # Logging (shared with portal)
  log_retention_days = var.log_retention_days

  # Container configuration
  guacd_image_tag                = var.guacd_image_tag
  guacamole_client_image_tag     = var.guacamole_client_image_tag
  guacd_cpu                      = var.guacd_cpu
  guacd_memory                   = var.guacd_memory
  guacamole_client_cpu           = var.guacamole_client_cpu
  guacamole_client_memory        = var.guacamole_client_memory
  guacd_desired_count            = var.guacd_desired_count
  guacamole_client_desired_count = var.guacamole_client_desired_count

  # Database configuration
  db_instance_class        = var.guacamole_db_instance_class
  db_allocated_storage     = var.guacamole_db_allocated_storage
  db_max_allocated_storage = var.guacamole_db_max_allocated_storage
  db_engine_version        = var.guacamole_db_engine_version
  db_multi_az              = var.guacamole_db_multi_az
  db_backup_retention_days = var.guacamole_db_backup_retention_days
  db_deletion_protection   = var.guacamole_db_deletion_protection
  db_skip_final_snapshot   = var.guacamole_db_skip_final_snapshot

  # Autoscaling
  enable_autoscaling       = var.guacamole_enable_autoscaling
  autoscaling_min_capacity = var.guacamole_autoscaling_min_capacity
  autoscaling_max_capacity = var.guacamole_autoscaling_max_capacity
  autoscaling_cpu_target   = var.guacamole_autoscaling_cpu_target

  # Secrets
  secrets_recovery_window_days = var.guacamole_secrets_recovery_window_days

  # OIDC/Cognito authentication
  enable_oidc          = var.guacamole_enable_oidc
  cognito_user_pool_id = module.cognito.user_pool_id
  cognito_domain       = module.cognito.cognito_domain
  aws_region           = var.aws_region
  domain_name          = var.domain_name
}

# ------------------------------------------------------------------------------
# PgBouncer (Database Connection Pooling)
# ------------------------------------------------------------------------------

module "pgbouncer" {
  source = "../../../modules/pgbouncer"

  name_prefix = local.name_prefix
  environment = var.environment
  tags        = var.tags

  # Networking (Portal VPC)
  vpc_id                               = module.vpc.vpc_id
  private_subnet_ids                   = module.vpc.private_subnet_ids
  portal_security_group_id             = module.ec2.security_group_id
  additional_client_security_group_ids = []

  # Database configuration
  rds_endpoint              = module.rds.db_instance_endpoint
  rds_security_group_id     = module.rds.db_security_group_id
  db_credentials_secret_arn = module.rds.db_credentials_secret_arn
  db_name                   = var.db_name

  # PgBouncer auth_query configuration (for SCRAM-SHA-256 support)
  auth_user_secret_arn = aws_secretsmanager_secret.pgbouncer_auth.arn

  # ECS configuration
  cpu           = var.pgbouncer_cpu
  memory        = var.pgbouncer_memory
  desired_count = var.pgbouncer_desired_count

  # PgBouncer configuration
  pool_mode         = var.pgbouncer_pool_mode
  max_client_conn   = var.pgbouncer_max_client_conn
  default_pool_size = var.pgbouncer_default_pool_size

  # Logging
  log_retention_days = var.log_retention_days
}

# ------------------------------------------------------------------------------
# PgBouncer Auth User Setup (via SSM to Portal EC2)
# ------------------------------------------------------------------------------
# Creates the pgbouncer_auth PostgreSQL user and get_auth() function.
# Must run via SSM because GitHub runner cannot reach RDS (private subnet).
# The portal EC2 has VPC access to RDS and psql installed.

resource "null_resource" "pgbouncer_auth_setup" {
  triggers = {
    # Re-run if password changes
    pgbouncer_auth_secret_version = aws_secretsmanager_secret_version.pgbouncer_auth.version_id
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail

      echo "Creating pgbouncer_auth user via SSM..."

      # Get an instance ID from the portal EC2 (supports both single instance and ASG)
      INSTANCE_ID=$(aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=${local.name_prefix}-ec2" \
                  "Name=instance-state-name,Values=running" \
        --query "Reservations[0].Instances[0].InstanceId" \
        --output text \
        --region ${var.aws_region})

      if [[ "$INSTANCE_ID" == "None" ]] || [[ -z "$INSTANCE_ID" ]]; then
        echo "ERROR: No running portal EC2 instance found with tag Name=${local.name_prefix}-ec2"
        exit 1
      fi

      echo "Found portal instance: $INSTANCE_ID"

      # Wait for instance to be SSM-ready and psql installed (user_data completion)
      echo "Waiting for instance to be SSM-ready..."
      for i in {1..60}; do
        SSM_STATUS=$(aws ssm describe-instance-information \
          --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
          --query "InstanceInformationList[0].PingStatus" \
          --output text \
          --region ${var.aws_region} 2>/dev/null || echo "Unknown")

        if [[ "$SSM_STATUS" == "Online" ]]; then
          echo "Instance is SSM-ready"
          break
        fi

        if [[ $i -eq 60 ]]; then
          echo "ERROR: Instance not SSM-ready after 5 minutes"
          exit 1
        fi

        echo "Waiting for SSM... (status: $SSM_STATUS)"
        sleep 5
      done

      # Send SSM command to create pgbouncer_auth user
      COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=[
          'set -euo pipefail',
          'for i in {1..30}; do which psql && break || sleep 5; done',
          'which psql || { echo ERROR: psql not found; exit 1; }',
          'echo Creating pgbouncer_auth user...',
          'export AWS_DEFAULT_REGION=${var.aws_region}',
          'DB_SECRET=$(aws secretsmanager get-secret-value --secret-id ${module.rds.db_credentials_secret_arn} --query SecretString --output text)',
          'DB_HOST=$(echo \$DB_SECRET | jq -r .host)',
          'DB_PORT=$(echo \$DB_SECRET | jq -r .port)',
          'DB_NAME=$(echo \$DB_SECRET | jq -r .dbname)',
          'DB_USER=$(echo \$DB_SECRET | jq -r .username)',
          'export PGPASSWORD=$(echo \$DB_SECRET | jq -r .password)',
          'AUTH_SECRET=$(aws secretsmanager get-secret-value --secret-id ${aws_secretsmanager_secret.pgbouncer_auth.arn} --query SecretString --output text)',
          'AUTH_PASSWORD=$(echo \$AUTH_SECRET | jq -r .password)',
          'psql -h \$DB_HOST -p \$DB_PORT -U \$DB_USER -d \$DB_NAME -v ON_ERROR_STOP=1 <<SQL',
          'DO \\$\\$',
          'BEGIN',
          '  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = ('\''pgbouncer_auth'\'')) THEN',
          '    EXECUTE format(('\''CREATE ROLE pgbouncer_auth WITH LOGIN PASSWORD %L'\''), ('\'''\$AUTH_PASSWORD'\''));',
          '  ELSE',
          '    EXECUTE format(('\''ALTER ROLE pgbouncer_auth WITH PASSWORD %L'\''), ('\'''\$AUTH_PASSWORD'\''));',
          '  END IF;',
          'END',
          '\\$\\$;',
          'CREATE SCHEMA IF NOT EXISTS pgbouncer AUTHORIZATION pgbouncer_auth;',
          'CREATE OR REPLACE FUNCTION pgbouncer.get_auth(p_username TEXT)',
          'RETURNS TABLE(username TEXT, password TEXT) AS',
          '\\$\\$',
          'BEGIN',
          '  RETURN QUERY',
          '  SELECT usename::TEXT, passwd::TEXT',
          '  FROM pg_shadow',
          '  WHERE usename = p_username;',
          'END;',
          '\\$\\$ LANGUAGE plpgsql SECURITY DEFINER;',
          'REVOKE ALL ON FUNCTION pgbouncer.get_auth(TEXT) FROM PUBLIC;',
          'GRANT EXECUTE ON FUNCTION pgbouncer.get_auth(TEXT) TO pgbouncer_auth;',
          'SQL',
          'echo pgbouncer_auth user created successfully'
        ]" \
        --query "Command.CommandId" \
        --output text \
        --region ${var.aws_region})

      echo "SSM Command ID: $COMMAND_ID"

      # Wait for command to complete (up to 2 minutes)
      for i in {1..24}; do
        STATUS=$(aws ssm get-command-invocation \
          --command-id "$COMMAND_ID" \
          --instance-id "$INSTANCE_ID" \
          --query "Status" \
          --output text \
          --region ${var.aws_region} 2>/dev/null || echo "Pending")

        if [[ "$STATUS" == "Success" ]]; then
          echo "pgbouncer_auth user setup completed successfully"
          exit 0
        elif [[ "$STATUS" == "Failed" ]] || [[ "$STATUS" == "Cancelled" ]] || [[ "$STATUS" == "TimedOut" ]]; then
          echo "ERROR: SSM command failed with status: $STATUS"
          aws ssm get-command-invocation \
            --command-id "$COMMAND_ID" \
            --instance-id "$INSTANCE_ID" \
            --query "StandardErrorContent" \
            --output text \
            --region ${var.aws_region}
          exit 1
        fi

        echo "Waiting for SSM command... (status: $STATUS)"
        sleep 5
      done

      echo "ERROR: SSM command timed out"
      exit 1
    EOT
  }

  depends_on = [
    module.ec2,
    module.rds,
    module.pgbouncer,
    aws_secretsmanager_secret_version.pgbouncer_auth,
  ]
}

# ------------------------------------------------------------------------------
# Log Aggregation (S3, SQS, Firehose for internal observability)
# Note: XDR CloudTrail integration is managed via CloudFormation, not Terraform
# ------------------------------------------------------------------------------

module "log_aggregation" {
  source = "../../../modules/log-aggregation"

  name_prefix            = local.name_prefix
  environment            = var.environment
  aws_region             = var.aws_region
  log_retention_days     = var.log_retention_days
  enable_log_aggregation = var.enable_log_aggregation

  # Phase 5: ALB and WAF logging
  enable_alb_access_logs = var.enable_alb_access_logs
  enable_waf_logging     = var.enable_waf_logging

  # Log group sources (for CloudWatch subscription filters)
  source_log_group_names = var.enable_log_aggregation ? concat(
    [module.ec2.log_group_name],
    [module.cognito.log_group_name],
    # Phase 5: VPC flow logs and RDS logs
    var.enable_vpc_flow_logs ? [module.vpc.flow_logs_log_group_name] : [],
    var.enable_rds_log_exports ? module.rds.log_group_names : [],
    # Pulumi provisioner logs
    module.pulumi_provisioner.log_group_names,
    # Guacamole logs
    module.guacamole.log_group_names,
  ) : []

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Bedrock Model Invocation Logging
# Captures invocation details including errors for debugging
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "bedrock" {
  count = var.enable_bedrock_logging ? 1 : 0

  name              = "/aws/bedrock/${local.name_prefix}-invocations"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-bedrock-invocations"
  })
}

resource "aws_iam_role" "bedrock_logging" {
  count = var.enable_bedrock_logging ? 1 : 0

  name = "${local.name_prefix}-bedrock-logging"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "bedrock.amazonaws.com"
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = var.enable_bedrock_logging ? 1 : 0

  name = "cloudwatch-logs"
  role = aws_iam_role.bedrock_logging[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "${aws_cloudwatch_log_group.bedrock[0].arn}:*"
    }]
  })
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enable_bedrock_logging ? 1 : 0

  logging_config {
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    text_data_delivery_enabled      = true

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock[0].name
      role_arn       = aws_iam_role.bedrock_logging[0].arn
    }
  }
}
