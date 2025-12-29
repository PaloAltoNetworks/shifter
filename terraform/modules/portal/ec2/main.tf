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
  log_group_name = "/portal/${var.name_prefix}"
}

# ------------------------------------------------------------------------------
# CloudWatch Log Group for Portal Container
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "portal" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-portal-logs"
  })
}

# ------------------------------------------------------------------------------
# IAM Role for EC2
# ------------------------------------------------------------------------------

resource "aws_iam_role" "this" {
  name = "${var.name_prefix}-ec2-role"

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
        Resource = "*"
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
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:shifter/*/range/*"
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
          "s3:DeleteObject"
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
        Resource = "*"
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

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name_prefix}-ec2-profile"
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

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.this.id
  description       = "Allow all outbound"
}

# ------------------------------------------------------------------------------
# AMI Lookup
# ------------------------------------------------------------------------------

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ------------------------------------------------------------------------------
# Launch Template (for ASG mode)
# ------------------------------------------------------------------------------

resource "aws_launch_template" "this" {
  count = var.enable_autoscaling ? 1 : 0

  name_prefix   = "${var.name_prefix}-lt-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.this.name
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.this.id]
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    aws_region         = var.aws_region
    ecr_repository_url = var.ecr_repository_url
    log_group_name     = local.log_group_name
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
      Name = "${var.name_prefix}-ec2"
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
  health_check_type         = "ELB"
  health_check_grace_period = 300

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
      min_healthy_percentage = 50
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

resource "aws_autoscaling_policy" "scale_up" {
  count = var.enable_autoscaling ? 1 : 0

  name                   = "${var.name_prefix}-scale-up"
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.this[0].name
}

resource "aws_autoscaling_policy" "scale_down" {
  count = var.enable_autoscaling ? 1 : 0

  name                   = "${var.name_prefix}-scale-down"
  scaling_adjustment     = -1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 300
  autoscaling_group_name = aws_autoscaling_group.this[0].name
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  count = var.enable_autoscaling ? 1 : 0

  alarm_name          = "${var.name_prefix}-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 120
  statistic           = "Average"
  threshold           = var.scale_up_threshold
  alarm_description   = "Scale up when CPU > ${var.scale_up_threshold}%"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.this[0].name
  }

  alarm_actions = [aws_autoscaling_policy.scale_up[0].arn]

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "cpu_low" {
  count = var.enable_autoscaling ? 1 : 0

  alarm_name          = "${var.name_prefix}-cpu-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 120
  statistic           = "Average"
  threshold           = var.scale_down_threshold
  alarm_description   = "Scale down when CPU < ${var.scale_down_threshold}%"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.this[0].name
  }

  alarm_actions = [aws_autoscaling_policy.scale_down[0].arn]

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# EC2 Instance (for single instance mode)
# ------------------------------------------------------------------------------

resource "aws_instance" "this" {
  count = var.enable_autoscaling ? 0 : 1

  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this.id]
  iam_instance_profile   = aws_iam_instance_profile.this.name
  monitoring             = true
  ebs_optimized          = true

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    aws_region         = var.aws_region
    ecr_repository_url = var.ecr_repository_url
    log_group_name     = local.log_group_name
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
    Name = "${var.name_prefix}-ec2"
  })

  lifecycle {
    ignore_changes = [ami]
  }
}
