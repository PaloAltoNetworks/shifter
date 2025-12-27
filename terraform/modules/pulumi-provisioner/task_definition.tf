# ------------------------------------------------------------------------------
# ECS Task Definition
# ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "pulumi_provisioner" {
  family                   = "${var.name_prefix}-pulumi-provisioner"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "pulumi-provisioner"
    image     = "${var.ecr_repository_url}:${var.container_image_tag}"
    essential = true

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = local.region },
      { name = "DB_HOST", value = var.db_host },
      { name = "DB_PORT", value = tostring(var.db_port) },
      { name = "DB_NAME", value = var.db_name },
      { name = "DB_USER", value = "provisioner_lambda" },
      { name = "PULUMI_BACKEND_URL", value = "s3://${var.pulumi_state_bucket}" },
      { name = "PULUMI_SECRETS_PROVIDER", value = "awskms://${var.pulumi_secrets_kms_key_alias}" },
      { name = "RANGE_VPC_ID", value = var.range_vpc_id },
      { name = "RANGE_VPC_CIDR", value = var.range_vpc_cidr },
      { name = "RANGE_ROUTE_TABLE_ID", value = var.range_route_table_id },
      { name = "RANGE_AVAILABILITY_ZONE", value = var.range_availability_zone },
      { name = "KALI_SECURITY_GROUP_ID", value = var.kali_security_group_id },
      { name = "VICTIM_SECURITY_GROUP_ID", value = var.victim_security_group_id },
      { name = "DC_SECURITY_GROUP_ID", value = var.dc_security_group_id },
      { name = "RANGE_INSTANCE_PROFILE_NAME", value = var.range_instance_profile_name },
      { name = "KALI_AMI_ID", value = var.kali_ami_id },
      { name = "VICTIM_AMI_ID", value = var.victim_ami_id },
      { name = "WINDOWS_AMI_ID", value = var.windows_ami_id },
      { name = "DC_AMI_ID", value = var.dc_ami_id },
      { name = "DC_DOMAIN_NAME", value = var.dc_domain_name },
      { name = "DC_DOMAIN_PASSWORD", value = var.dc_domain_password },
      { name = "AGENT_S3_BUCKET", value = var.agent_s3_bucket },
      { name = "KALI_INSTANCE_TYPE", value = var.kali_instance_type },
      { name = "VICTIM_INSTANCE_TYPE", value = var.victim_instance_type },
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
