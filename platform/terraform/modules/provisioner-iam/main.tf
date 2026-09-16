# Substrate-neutral Shifter provisioner IAM (#1826).
#
# The Shifter provisioner performs identical AWS work whether it runs as an ECS
# Fargate task (legacy) or an EKS Kubernetes Job (the management-plane default).
# This module is the single source of truth for the privileged provisioner's AWS
# permission set, attached to a caller-supplied role: the ECS task role
# (modules/engine-provisioner) or the EKS provisioner IRSA role
# (modules/portal/eks). The large EC2 / RunInstances / GWLB policies are managed
# (attached by ARN) to stay under the 10,240-byte per-role inline aggregate; the
# smaller policies are inline on the caller's role. Both together stay under the
# per-role managed-policy count limit.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.id
}

# ------------------------------------------------------------------------------
# Managed policy - EC2 provisioning (lifecycle + networking)
# ------------------------------------------------------------------------------

resource "aws_iam_policy" "ec2_provisioning" {
  name        = "${var.name_prefix}-pulumi-ec2-provisioning-managed"
  description = "Shifter provisioner EC2 lifecycle and networking permissions (managed to stay under the role inline-policy size limit)."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ec2:Describe*"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:ImportKeyPair", "ec2:DeleteKeyPair"]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:key-pair/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:CreateTags"]
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
        Effect = "Allow"
        Action = [
          "ec2:TerminateInstances",
          "ec2:StopInstances",
          "ec2:StartInstances",
          "ec2:ModifyInstanceAttribute",
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
        Effect = "Allow"
        Action = [
          "ec2:CreateNatGateway",
          "ec2:DeleteNatGateway",
          "ec2:DescribeNatGateways"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = compact([var.range_instance_role_arn, var.ngfw_instance_role_arn])
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ec2_provisioning" {
  role       = var.role_name
  policy_arn = aws_iam_policy.ec2_provisioning.arn
}

# ------------------------------------------------------------------------------
# Managed policy - EC2 RunInstances (image/volume/dependent-network scoped)
# ------------------------------------------------------------------------------

resource "aws_iam_policy" "ec2_run_instances" {
  name        = "${var.name_prefix}-pulumi-ec2-run-instances-managed"
  description = "Allows the Shifter provisioner to launch range and NGFW instances with scoped dependent resources."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ec2:RunInstances"]
        Resource = ["arn:aws:ec2:${local.region}:${local.account_id}:instance/*"]
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:RunInstances"]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:volume/*"
        Condition = {
          StringEquals = {
            "ec2:AvailabilityZone" = var.range_availability_zone
          }
          Bool = {
            "aws:ResourceBeingCreated" = "true"
            "ec2:Encrypted"            = "true"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:RunInstances"]
        Resource = "arn:aws:ec2:${local.region}::image/*"
        Condition = {
          StringEquals = {
            "ec2:Owner" = local.account_id
          }
        }
      },
      {
        Effect = "Allow"
        Action = ["ec2:RunInstances"]
        Resource = [
          "arn:aws:ec2:${local.region}:${local.account_id}:network-interface/*",
          "arn:aws:ec2:${local.region}:${local.account_id}:subnet/*",
          "arn:aws:ec2:${local.region}:${local.account_id}:security-group/*"
        ]
        Condition = {
          ArnEquals = {
            "ec2:Vpc" = "arn:aws:ec2:${local.region}:${local.account_id}:vpc/${var.range_vpc_id}"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:RunInstances"]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:key-pair/*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/shifter:system"      = "shifter"
            "ec2:ResourceTag/shifter:environment" = var.environment
            "ec2:ResourceTag/ManagedBy"           = "terraform"
          }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ec2_run_instances" {
  role       = var.role_name
  policy_arn = aws_iam_policy.ec2_run_instances.arn
}

# ------------------------------------------------------------------------------
# Managed policy - Gateway Load Balancer (GWLB) for NGFW traffic steering
# ------------------------------------------------------------------------------

resource "aws_iam_policy" "gwlb" {
  name        = "${var.name_prefix}-pulumi-gwlb-provisioning-managed"
  description = "Shifter provisioner Gateway Load Balancer permissions (managed to stay under the role inline-policy size limit)."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeLoadBalancerAttributes",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetGroupAttributes",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeListeners",
          "elasticloadbalancing:DescribeListenerAttributes",
          "elasticloadbalancing:DescribeTags"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:CreateTargetGroup",
          "elasticloadbalancing:CreateListener"
        ]
        Resource = [
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
        ]
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:ModifyTargetGroupAttributes",
          "elasticloadbalancing:SetSecurityGroups",
          "elasticloadbalancing:RemoveTags"
        ]
        Resource = [
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
        ]
        Condition = {
          StringEquals = {
            "elasticloadbalancing:ResourceTag/shifter:system"      = "shifter"
            "elasticloadbalancing:ResourceTag/shifter:environment" = var.environment
            "elasticloadbalancing:ResourceTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect = "Allow"
        Action = ["elasticloadbalancing:AddTags"]
        Resource = [
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
        ]
        Condition = {
          StringEquals = {
            "elasticloadbalancing:CreateAction" = [
              "CreateLoadBalancer",
              "CreateTargetGroup",
              "CreateListener"
            ]
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = "elasticloadbalancing:CreateLoadBalancer"
        Resource = "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = "elasticloadbalancing:CreateListener"
        Resource = "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"                        = "shifter"
            "aws:RequestTag/shifter:environment"                   = var.environment
            "aws:RequestTag/ManagedBy"                             = "terraform"
            "elasticloadbalancing:ResourceTag/shifter:system"      = "shifter"
            "elasticloadbalancing:ResourceTag/shifter:environment" = var.environment
            "elasticloadbalancing:ResourceTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect   = "Allow"
        Action   = "elasticloadbalancing:CreateTargetGroup"
        Resource = "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/shifter-vpn-*/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:RegisterTargets",
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:ModifyTargetGroupAttributes",
          "elasticloadbalancing:SetSecurityGroups",
          "elasticloadbalancing:RemoveTags"
        ]
        Resource = [
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/net/shifter-vpn-*/*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/shifter-vpn-*/*"
        ]
        Condition = {
          StringEquals = {
            "elasticloadbalancing:ResourceTag/shifter:system"      = "shifter"
            "elasticloadbalancing:ResourceTag/shifter:environment" = var.environment
            "elasticloadbalancing:ResourceTag/ManagedBy"           = "terraform"
          }
        }
      },
      {
        Effect = "Allow"
        Action = "elasticloadbalancing:AddTags"
        Resource = [
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/net/shifter-vpn-*/*/*",
          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/shifter-vpn-*/*"
        ]
        Condition = {
          StringEquals = {
            "elasticloadbalancing:CreateAction" = [
              "CreateLoadBalancer",
              "CreateTargetGroup",
              "CreateListener"
            ]
            "aws:RequestTag/shifter:system"      = "shifter"
            "aws:RequestTag/shifter:environment" = var.environment
            "aws:RequestTag/ManagedBy"           = "terraform"
          }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "gwlb" {
  role       = var.role_name
  policy_arn = aws_iam_policy.gwlb.arn
}

# ------------------------------------------------------------------------------
# Inline policies - smaller scoped grants (kept inline to stay under the
# per-role managed-policy count limit; aggregate stays under 10,240 bytes).
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "engine_state" {
  name = "pulumi-state"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [var.engine_state_bucket_arn, "${var.engine_state_bucket_arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = var.engine_locks_table_arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "secrets_manager" {
  name = "secrets-manager"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:CreateSecret",
        "secretsmanager:TagResource",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetResourcePolicy",
        "secretsmanager:DeleteSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:GetSecretValue",
        "secretsmanager:ListSecretVersionIds",
        "secretsmanager:UpdateSecretVersionStage"
      ]
      Resource = [
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:shifter/${var.environment}/range/*",
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:shifter/${var.environment}/vpn-issuer/*",
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:shifter/${var.environment}/ngfw/*"
      ]
    }]
  })
}

resource "aws_iam_role_policy" "rds_iam_auth" {
  name = "rds-iam-auth"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = "arn:aws:rds-db:${local.region}:${local.account_id}:dbuser:${var.db_resource_id}/provisioner_lambda"
    }]
  })
}

resource "aws_iam_role_policy" "s3_agent" {
  name = "s3-agent-read"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [var.agent_s3_bucket_arn, "${var.agent_s3_bucket_arn}/*"]
    }]
  })
}

resource "aws_iam_role_policy" "vpc_endpoints" {
  name = "vpc-endpoints"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
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

resource "aws_iam_role_policy" "s3_bootstrap" {
  name = "s3-bootstrap-write"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObjectTagging"]
      Resource = "${var.agent_s3_bucket_arn}/bootstrap/*"
    }]
  })
}

resource "aws_iam_role_policy" "ssm_parameters" {
  name = "ssm-parameters"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParameterHistory",
          "ssm:DeleteParameter",
          "ssm:AddTagsToResource",
          "ssm:ListTagsForResource",
          "ssm:RemoveTagsFromResource"
        ]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/shifter/${var.environment}/range/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/shifter/ami/*"
      },
      {
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
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

resource "aws_iam_role_policy" "ssm_run_command" {
  name = "ssm-run-command"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:SendCommand"]
        Resource = ["arn:aws:ec2:${local.region}:${local.account_id}:instance/*"]
        Condition = {
          StringEquals = {
            "ssm:resourceTag/shifter:system"      = "shifter"
            "ssm:resourceTag/shifter:environment" = var.environment
          }
          Null = {
            "ssm:resourceTag/shifter:range_id" = "false"
          }
        }
      },
      {
        Effect = "Allow"
        Action = ["ssm:SendCommand"]
        Resource = [
          "arn:aws:ssm:${local.region}::document/AWS-RunPowerShellScript",
          "arn:aws:ssm:${local.region}::document/AWS-RunShellScript"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:DescribeInstanceInformation"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:RebootInstances"]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/shifter:system"      = "shifter"
            "ec2:ResourceTag/shifter:environment" = var.environment
            "ec2:ResourceTag/ManagedBy"           = "terraform"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "kms" {
  name = "kms-access"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource = var.engine_secrets_kms_key_arn
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
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

resource "aws_iam_role_policy" "polaris_agent_role_management" {
  name = "polaris-agent-role-management"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CreatePolarisAgentRoleWithBoundary"
        Effect   = "Allow"
        Action   = "iam:CreateRole"
        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-polaris-agent"
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = var.permissions_boundary_arn
          }
        }
      },
      {
        Sid    = "ManagePolarisAgentRole"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:ListRoleTags"
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-polaris-agent"
      }
    ]
  })
}

resource "aws_iam_role_policy" "vpn_gateway_role_management" {
  name = "vpn-gateway-role-management"
  role = var.role_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CreateVpnGatewayRoleWithBoundary"
        Effect   = "Allow"
        Action   = "iam:CreateRole"
        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = var.permissions_boundary_arn
          }
        }
      },
      {
        Sid    = "ManageVpnGatewayRole"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:ListRoleTags"
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
      },
      {
        Sid      = "UseOnlySsmCorePolicy"
        Effect   = "Allow"
        Action   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
        Condition = {
          ArnEquals = {
            "iam:PolicyARN" = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
          }
        }
      },
      {
        Sid    = "ManageVpnGatewayInstanceProfile"
        Effect = "Allow"
        Action = [
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:UntagInstanceProfile"
        ]
        Resource = "arn:aws:iam::${local.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway"
      },
      {
        Sid      = "PassVpnGatewayRoleOnlyToEc2"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ec2.amazonaws.com"
          }
        }
      }
    ]
  })
}
