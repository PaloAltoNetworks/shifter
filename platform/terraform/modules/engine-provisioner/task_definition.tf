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

  # Issue #1103: dedicated writable volumes so the container can run with
  # readonlyRootFilesystem = true. Fargate creates these from the task's
  # ephemeral storage (no host_path), which is fine for Terraform staging
  # and tool caches that should not persist across task restarts.
  #
  # Ownership contract — these volumes have NO `host` block and NO
  # `host_path`, so AWS/Fargate creates a Docker named-volume on the
  # task's ephemeral storage. Docker named-volume semantics (which AWS
  # Fargate inherits) initialize the volume from the image's directory at
  # the mount point: contents AND ownership/permissions are copied from
  # the image dir at mount time. The Dockerfile pre-creates each of these
  # paths (`/var/run/provisioner/workspace`, `/tmp`,
  # `/home/appuser/.terraform.d/plugin-cache`, `/home/appuser/.pulumi`)
  # with `mkdir` + `chown -R appuser:appgroup`, so the named volume comes
  # up owned by uid/gid 1000 and the non-root container can write
  # immediately. This is the AWS-native equivalent of the GKE
  # `fsGroup: 1000` we set on the Pod spec — different mechanism, same
  # outcome. End-to-end dev verification (per the issue's acceptance
  # criterion) is the conclusive cross-check.
  # See: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/specify-bind-mount-config.html
  volume {
    name = "provisioner-workspace"
  }
  volume {
    name = "tmp"
  }
  volume {
    name = "tf-plugin-cache"
  }
  volume {
    name = "pulumi-home"
  }

  container_definitions = jsonencode([{
    name                   = "pulumi-provisioner"
    image                  = "${var.ecr_repository_url}:${var.container_image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    # Defense-in-depth: the image's USER directive already drops to UID/GID
    # 1000, but declaring it on the task definition makes the contract
    # explicit and guards against an image where USER was omitted. The
    # mountPoints below resolve to ephemeral Fargate volumes that inherit
    # the image directory's ownership (appuser:appgroup, pre-chowned in
    # the Dockerfile), so writes by UID 1000 succeed without an init-chown.
    user = "1000:1000"

    mountPoints = [
      { sourceVolume = "provisioner-workspace", containerPath = "/var/run/provisioner/workspace", readOnly = false },
      { sourceVolume = "tmp", containerPath = "/tmp", readOnly = false },
      { sourceVolume = "tf-plugin-cache", containerPath = "/home/appuser/.terraform.d/plugin-cache", readOnly = false },
      { sourceVolume = "pulumi-home", containerPath = "/home/appuser/.pulumi", readOnly = false },
    ]

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
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
      { name = "RANGE_INSTANCE_PROFILE_NAME", value = var.range_instance_profile_name },
      { name = "KALI_AMI_ID", value = var.kali_ami_id },
      { name = "VICTIM_AMI_ID", value = var.victim_ami_id },
      { name = "WINDOWS_AMI_ID", value = var.windows_ami_id },
      { name = "DC_AMI_ID", value = var.dc_ami_id },
      { name = "DC_DOMAIN_NAME", value = var.dc_domain_name },
      { name = "AGENT_S3_BUCKET", value = var.agent_s3_bucket },
      { name = "S3_ENDPOINT_ID", value = var.s3_endpoint_id },
      { name = "FIREWALL_ENDPOINT_ID", value = var.firewall_endpoint_id },
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
    ]

    secrets = [
      {
        name      = "DC_DOMAIN_PASSWORD"
        valueFrom = data.aws_secretsmanager_secret.dc_domain_password.arn
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
