# ------------------------------------------------------------------------------
# ECS Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "engine_provisioner" {
  family                   = "${var.name_prefix}-pulumi-provisioner"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "pulumi-provisioner"
    image     = var.container_image_digest != "" ? "${var.ecr_repository_url}@${var.container_image_digest}" : "${var.ecr_repository_url}:${var.container_image_tag}"
    essential = true
    # Keep the ECS task non-root. AWS Fargate task volumes are mounted
    # root-owned and do not expose a Kubernetes-style fsGroup / uid option,
    # so readonlyRootFilesystem + non-root + mounted /tmp/workspace paths
    # leaves Python with no usable temp directory. The image still keeps
    # application code root-owned and unwritable to UID 1000; writable
    # paths are limited to /tmp, HOME tool caches, and
    # TERRAFORM_WORKSPACE_DIR inside the task's ephemeral writable layer.
    readonlyRootFilesystem = false
    user                   = "1000:1000"

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      # Explicit backend selection for the provisioner (PLAT-2005). The AWS
      # provisioner previously relied on the runtime's implicit "aws" default;
      # runtime now fails closed on a missing/unsupported backend, so every
      # deployed role must receive the value explicitly. Renderer-owned: the
      # value comes from var.cloud_provider (rendered from shifter.yaml at
      # deploy time), not a hardcoded literal.
      { name = "CLOUD_PROVIDER", value = var.cloud_provider },
      { name = "SECRETS_KMS_KEY_ARN", value = var.secrets_manager_kms_key_arn },
      { name = "AWS_REGION", value = local.region },
      { name = "DB_HOST", value = var.db_host },
      { name = "DB_PORT", value = tostring(var.db_port) },
      { name = "DB_NAME", value = var.db_name },
      { name = "DB_USER", value = "provisioner_lambda" },
      { name = "STATE_BUCKET_URL", value = "s3://${var.engine_state_bucket}" },
      { name = "RANGE_VPC_ID", value = var.range_vpc_id },
      { name = "RANGE_VPC_CIDR", value = var.range_vpc_cidr },
      { name = "RANGE_ROUTE_TABLE_ID", value = var.range_route_table_id },
      { name = "RANGE_AVAILABILITY_ZONE", value = var.range_availability_zone },
      { name = "RANGE_VPN_EDGE_SUBNET_ID", value = var.range_vpn_edge_subnet_id },
      { name = "RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN", value = var.permissions_boundary_arn },
      { name = "RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID", value = var.range_vpn_provider_endpoint_security_group_id },
      { name = "RANGE_INSTANCE_PROFILE_NAME", value = var.range_instance_profile_name },
      { name = "KALI_AMI_ID", value = var.kali_ami_id },
      { name = "VICTIM_AMI_ID", value = var.victim_ami_id },
      { name = "WINDOWS_AMI_ID", value = var.windows_ami_id },
      { name = "DC_AMI_ID", value = var.dc_ami_id },
      { name = "DC_DOMAIN_NAME", value = var.dc_domain_name },
      { name = "AGENT_S3_BUCKET", value = var.agent_s3_bucket },
      { name = "S3_ENDPOINT_ID", value = var.s3_endpoint_id },
      { name = "FIREWALL_ENDPOINT_ID", value = var.firewall_endpoint_id },
      { name = "RANGE_EGRESS_MODE", value = var.range_egress_mode },
      { name = "SSM_ENDPOINTS_SUBNET_CIDR", value = var.ssm_endpoints_subnet_cidr },
      { name = "PORTAL_VPC_CIDR", value = var.portal_vpc_cidr },
      { name = "PORTAL_VPC_PEERING_ID", value = var.portal_vpc_peering_id },
      { name = "KALI_INSTANCE_TYPE", value = var.kali_instance_type },
      { name = "VICTIM_INSTANCE_TYPE", value = var.victim_instance_type },
      # NGFW (VM-Series) configuration
      { name = "NGFW_AMI_ID", value = var.ngfw_ami_id },
      { name = "NGFW_INSTANCE_TYPE", value = var.ngfw_instance_type },
      { name = "NGFW_MGMT_SECURITY_GROUP_ID", value = var.ngfw_mgmt_security_group_id },
      { name = "NGFW_DATA_SECURITY_GROUP_ID", value = var.ngfw_data_security_group_id },
      { name = "NGFW_VPC_ID", value = var.range_vpc_id },
      { name = "NGFW_SUBNET_ID", value = var.ngfw_subnet_id },
      { name = "NGFW_SUBNET_CIDR", value = var.ngfw_subnet_cidr },
      { name = "NGFW_BOOTSTRAP_BUCKET", value = var.agent_s3_bucket },
      { name = "NGFW_INSTANCE_PROFILE_NAME", value = var.ngfw_instance_profile_name },
      # Messaging (SNS for range events)
      { name = "SNS_RANGE_EVENTS_ARN", value = var.sns_topic_arn },
      # Polaris Bedrock agent config (#1377). See
      # shifter/engine/provisioner/config.py load_aws_polaris_agent_config().
      # RANGE_INSTANCE_ROLE_ARN reuses the existing shared range-host role
      # ARN (already granted iam:PassRole above) as the per-range Polaris
      # agent role's trust principal.
      { name = "AWS_POLARIS_AGENT_REGION", value = var.aws_polaris_agent_region },
      { name = "AWS_POLARIS_AGENT_MAIN_MODEL_ID", value = var.aws_polaris_agent_main_model_id },
      { name = "AWS_POLARIS_AGENT_SMALL_MODEL_ID", value = var.aws_polaris_agent_small_model_id },
      { name = "AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN", value = var.aws_polaris_agent_main_inference_profile_arn },
      { name = "AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN", value = var.aws_polaris_agent_small_inference_profile_arn },
      { name = "AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS", value = join(",", var.aws_polaris_agent_main_backing_model_arns) },
      { name = "AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS", value = join(",", var.aws_polaris_agent_small_backing_model_arns) },
      { name = "AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS", value = tostring(var.aws_polaris_agent_sts_session_duration_seconds) },
      { name = "AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS", value = tostring(var.aws_polaris_agent_refresh_window_seconds) },
      { name = "AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN", value = var.permissions_boundary_arn },
      { name = "RANGE_INSTANCE_ROLE_ARN", value = var.range_instance_role_arn },
    ]

    secrets = [
      {
        name      = "DC_DOMAIN_PASSWORD"
        valueFrom = aws_secretsmanager_secret.dc_domain_password.arn
      }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = local.region
        "awslogs-stream-prefix" = "pulumi"
      }
    }
  }])

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-provisioner"
  })
}
