# ------------------------------------------------------------------------------
# ECS Execution Role
# ------------------------------------------------------------------------------
# Used by ECS to pull container images and write logs

resource "aws_iam_role" "ecs_execution" {
  name = "${var.name_prefix}-pulumi-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_ecr" {
  name = "ecr-pull"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ]
      Resource = "*"
    }]
  })
}

# Allow the ECS execution role to fetch the DC domain password secret so
# ECS can hydrate the DC_DOMAIN_PASSWORD container env var via the
# `secrets = [...]` block in task_definition.tf.
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "secrets-read"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = [
        aws_secretsmanager_secret.dc_domain_password.arn
      ]
    }]
  })
}

# ------------------------------------------------------------------------------
# ECS Task Role
# ------------------------------------------------------------------------------
# Used by the engine provisioner container for AWS operations

resource "aws_iam_role" "ecs_task" {
  name = "${var.name_prefix}-pulumi-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Task Role Policy - Engine State
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "engine_state" {
  name = "pulumi-state"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.engine_state_bucket_arn,
          "${var.engine_state_bucket_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ]
        Resource = var.engine_locks_table_arn
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - EC2 Provisioning
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "ec2_provisioning" {
  name = "ec2-provisioning"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # EC2 read and key-pair operations. Describe APIs require
        # Resource=*; key-pair names are generated per range/NGFW run.
        Sid    = "EC2DescribeAndKeyPairOperations"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "ec2:ImportKeyPair",
          "ec2:DeleteKeyPair"
        ]
        Resource = "*"
      },
      {
        # Instance creation is restricted by the runtime Terraform tags that
        # the provisioner applies to every managed range/NGFW instance.
        Sid    = "EC2TaggedInstanceCreate"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        # Tagging at create time is needed for the EC2 resources provisioner
        # Terraform creates and is bound to create APIs so it cannot retag
        # arbitrary EC2 resources.
        Sid    = "EC2TagOnCreate"
        Effect = "Allow"
        Action = [
          "ec2:CreateTags"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:CreateAction" = [
              "AllocateAddress",
              "CreateInternetGateway",
              "CreateNatGateway",
              "CreateNetworkInterface",
              "CreateRouteTable",
              "CreateSecurityGroup",
              "CreateSubnet",
              "CreateVpcEndpoint",
              "CreateVpcEndpointServiceConfiguration",
              "ImportKeyPair",
              "RunInstances"
            ]
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        # EC2 instance lifecycle management for provisioner-owned instances.
        # - TerminateInstances for destroy
        # - StopInstances, StartInstances for power management
        # - ModifyInstanceAttribute for runtime changes
        # - DeleteTags for cleanup
        Sid    = "EC2TaggedInstanceLifecycle"
        Effect = "Allow"
        Action = [
          "ec2:TerminateInstances",
          "ec2:StopInstances",
          "ec2:StartInstances",
          "ec2:ModifyInstanceAttribute",
          # ModifyInstanceMetadataOptions is required so the polaris
          # range bootstrap can set HttpPutResponseHopLimit=2 on the
          # polaris-vm — without that the a14-kali docker container
          # can't reach IMDS for instance-profile credentials and the
          # claude/Bedrock smoke test fails.
          "ec2:ModifyInstanceMetadataOptions",
          "ec2:DeleteTags"
        ]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/shifter:system"      = "shifter"
            "ec2:ResourceTag/shifter:environment" = var.environment
            "ec2:ResourceTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        # Network interface operations for NGFW ENI creation
        # - CreateNetworkInterface for mgmt and data ENIs
        # - ModifyNetworkInterfaceAttribute for source_dest_check=False on data ENI
        # - DeleteNetworkInterface for cleanup
        Sid    = "EC2NetworkInterfaceOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DeleteNetworkInterface",
          "ec2:DetachNetworkInterface",
          "ec2:ModifyNetworkInterfaceAttribute"
        ]
        Resource = "*"
      },
      {
        # Full subnet lifecycle management
        # - CreateSubnet, DeleteSubnet for create/destroy
        # - ModifySubnetAttribute for map_public_ip_on_launch, etc.
        # - DescribeSubnets for state queries
        # Note: tag-on-create support is in EC2TagOnCreate.
        Sid    = "EC2SubnetOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateSubnet",
          "ec2:DeleteSubnet",
          "ec2:ModifySubnetAttribute",
          "ec2:DescribeSubnets"
        ]
        Resource = "*"
      },
      {
        # Route Table lifecycle management
        # - CreateRouteTable, DeleteRouteTable for create/destroy
        # - CreateRoute, DeleteRoute, ReplaceRoute for route entries
        # - AssociateRouteTable, DisassociateRouteTable for subnet associations
        # - DescribeRouteTables for state queries
        Sid    = "EC2RouteTableOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateRouteTable",
          "ec2:DeleteRouteTable",
          "ec2:CreateRoute",
          "ec2:DeleteRoute",
          "ec2:ReplaceRoute",
          "ec2:AssociateRouteTable",
          "ec2:DisassociateRouteTable",
          "ec2:DescribeRouteTables"
        ]
        Resource = "*"
      },
      {
        # Security Group lifecycle management
        # - CreateSecurityGroup, DeleteSecurityGroup for create/destroy
        # - AuthorizeSecurityGroupIngress/Egress for inbound/outbound rules
        # - RevokeSecurityGroupIngress/Egress for rule removal
        # Note: DescribeSecurityGroups covered by Describe* in EC2InstanceOperations
        Sid    = "EC2SecurityGroupOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateSecurityGroup",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupEgress"
        ]
        Resource = "*"
      },
      {
        # Internet Gateway lifecycle management
        # Required for routing traffic to/from the internet
        Sid    = "EC2InternetGatewayOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateInternetGateway",
          "ec2:DeleteInternetGateway",
          "ec2:AttachInternetGateway",
          "ec2:DetachInternetGateway",
          "ec2:DescribeInternetGateways"
        ]
        Resource = "*"
      },
      {
        # Elastic IP lifecycle management
        # Required for static public IPs on instances/NAT gateways
        Sid    = "EC2ElasticIPOperations"
        Effect = "Allow"
        Action = [
          "ec2:AllocateAddress",
          "ec2:ReleaseAddress",
          "ec2:AssociateAddress",
          "ec2:DisassociateAddress",
          "ec2:DescribeAddresses"
        ]
        Resource = "*"
      },
      {
        # NAT Gateway lifecycle management
        # Required for private subnet outbound internet access
        Sid    = "EC2NATGatewayOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateNatGateway",
          "ec2:DeleteNatGateway",
          "ec2:DescribeNatGateways"
        ]
        Resource = "*"
      },
      {
        # PassRole for range instances and NGFW instances
        # compact() filters out empty strings when NGFW is not enabled
        Sid    = "PassRoleToInstances"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = compact([
          var.range_instance_role_arn,
          var.ngfw_instance_role_arn
        ])
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - Secrets Manager
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "secrets_manager" {
  name = "secrets-manager"
  role = aws_iam_role.ecs_task.id

  # Permissions based on Terraform AWS provider source code analysis:
  # - secret.go: CreateSecret, DescribeSecret, GetResourcePolicy, DeleteSecret
  # - secret_version.go: PutSecretValue, GetSecretValue, ListSecretVersionIds, UpdateSecretVersionStage
  # Ref: github.com/hashicorp/terraform-provider-aws/internal/service/secretsmanager/
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        # secret.go - resourceSecretCreate, resourceSecretRead, resourceSecretDelete
        "secretsmanager:CreateSecret",
        "secretsmanager:TagResource",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetResourcePolicy",
        "secretsmanager:DeleteSecret",
        # secret_version.go - resourceSecretVersionCreate, resourceSecretVersionRead, resourceSecretVersionDelete
        "secretsmanager:PutSecretValue",
        "secretsmanager:GetSecretValue",
        "secretsmanager:ListSecretVersionIds",
        "secretsmanager:UpdateSecretVersionStage"
      ]
      Resource = [
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:shifter/${var.environment}/range/*",
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:shifter/${var.environment}/ngfw/*"
      ]
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - RDS IAM Authentication
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "rds_iam_auth" {
  name = "rds-iam-auth"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = "arn:aws:rds-db:${local.region}:${local.account_id}:dbuser:${var.db_resource_id}/provisioner_lambda"
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - S3 Agent Bucket
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "s3_agent" {
  name = "s3-agent-read"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        var.agent_s3_bucket_arn,
        "${var.agent_s3_bucket_arn}/*"
      ]
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - Gateway Load Balancer (GWLB)
# ------------------------------------------------------------------------------
# Provisioner creates GWLB infrastructure for NGFW traffic steering:
# - Gateway Load Balancer
# - Target groups with GENEVE protocol
# - Listeners

resource "aws_iam_role_policy" "gwlb" {
  name = "gwlb-provisioning"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GWLBOperations"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:CreateTargetGroup",
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:CreateListener",
          "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:ModifyTargetGroupAttributes",
          "elasticloadbalancing:AddTags",
          "elasticloadbalancing:RemoveTags"
        ]
        Resource = "*"
      },
      {
        Sid    = "GWLBDescribe"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:Describe*"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - VPC Endpoints
# ------------------------------------------------------------------------------
# Provisioner creates:
# - VPC Endpoint Services for GWLB connectivity from ranges (gwlb_component.py)
# - VPC Endpoints (GatewayLoadBalancer type) in range subnets (network.py)

resource "aws_iam_role_policy" "vpc_endpoints" {
  name = "vpc-endpoints"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # VPC Endpoint Service operations (for GWLB service exposure)
        Sid    = "VPCEndpointServiceOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateVpcEndpointServiceConfiguration",
          "ec2:DeleteVpcEndpointServiceConfigurations",
          "ec2:ModifyVpcEndpointServiceConfiguration",
          "ec2:ModifyVpcEndpointServicePermissions",
          "ec2:DescribeVpcEndpointServiceConfigurations",
          "ec2:DescribeVpcEndpointServicePermissions",
          "ec2:AcceptVpcEndpointConnections",
          "ec2:RejectVpcEndpointConnections"
        ]
        Resource = "*"
      },
      {
        # VPC Endpoint operations (for GWLB endpoints in range subnets)
        Sid    = "VPCEndpointOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateVpcEndpoint",
          "ec2:DeleteVpcEndpoints",
          "ec2:ModifyVpcEndpoint",
          "ec2:DescribeVpcEndpoints"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - S3 Bootstrap Write
# ------------------------------------------------------------------------------
# Provisioner needs write access to bootstrap/* prefix for NGFW init-cfg.txt,
# authcodes, and other bootstrap configuration files.

resource "aws_iam_role_policy" "s3_bootstrap" {
  name = "s3-bootstrap-write"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:GetObjectTagging"
      ]
      Resource = "${var.agent_s3_bucket_arn}/bootstrap/*"
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - SSM Parameters (DC Config)
# ------------------------------------------------------------------------------
# DC component creates SSM parameters to store domain config (credentials, etc.)
# that domain members retrieve during setup.

resource "aws_iam_role_policy" "ssm_parameters" {
  name = "ssm-parameters"
  role = aws_iam_role.ecs_task.id

  # Permissions based on AWS docs for SSM Parameter Store:
  # https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-access.html
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMParameterOperations"
        Effect = "Allow"
        Action = [
          # Create/Update
          "ssm:PutParameter",
          # Read
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParameterHistory",
          # Delete
          "ssm:DeleteParameter",
          # Tagging
          "ssm:AddTagsToResource",
          "ssm:ListTagsForResource",
          "ssm:RemoveTagsFromResource"
        ]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/shifter/${var.environment}/range/*"
      },
      {
        # Read-only access to AMI parameters (set by Packer builds)
        Sid    = "SSMReadAMIParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/shifter/ami/*"
      },
      {
        # DescribeParameters required by Terraform for metadata lookup
        # Must be * resource per AWS API requirements
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
      {
        # KMS permissions for SecureString parameters
        # Uses AWS managed key for SSM via service condition
        Sid    = "KMSForSecureStringParameters"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${local.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - SSM Run Command (for DC setup orchestration)
# ------------------------------------------------------------------------------
# Engine provisioner uses SSM Run Command to orchestrate DC setup:
# - Install AD DS feature
# - Reboot and wait for instance
# - Promote to Domain Controller
# - Verify AD DS is running

resource "aws_iam_role_policy" "ssm_run_command" {
  name = "ssm-run-command"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMSendCommand"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand"
        ]
        Resource = [
          "arn:aws:ec2:${local.region}:${local.account_id}:instance/*",
          "arn:aws:ssm:${local.region}::document/AWS-RunPowerShellScript",
          "arn:aws:ssm:${local.region}::document/AWS-RunShellScript"
        ]
      },
      {
        Sid    = "SSMGetCommandInvocation"
        Effect = "Allow"
        Action = [
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations"
        ]
        Resource = "*"
      },
      {
        Sid    = "SSMDescribeInstances"
        Effect = "Allow"
        Action = [
          "ssm:DescribeInstanceInformation"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2RebootInstances"
        Effect = "Allow"
        Action = [
          "ec2:RebootInstances"
        ]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - KMS (for engine secrets encryption)
# ------------------------------------------------------------------------------
# The engine's awskms:// secrets provider calls KMS directly (not via Secrets Manager),
# so we need separate statements for each use case.

resource "aws_iam_role_policy" "kms" {
  name = "kms-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EngineSecretsEncryption"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        # Dedicated CMK for engine stack secrets encryption
        Resource = var.engine_secrets_kms_key_arn
      },
      {
        Sid    = "SecretsManagerKMSAccess"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${local.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - SNS (for range event publishing)
# ------------------------------------------------------------------------------
# Provisioner publishes range lifecycle events to SNS for fan-out to
# Django services (CMS, Engine, Mission Control).

resource "aws_iam_role_policy" "sns_publish" {
  name = "sns-publish"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SNSPublishRangeEvents"
      Effect = "Allow"
      Action = [
        "sns:Publish"
      ]
      Resource = var.sns_topic_arn
    }]
  })
}
