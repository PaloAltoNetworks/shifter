# AWS Load Balancer Controller v3.2.2 permissions. The controller policy is
# owned beside its exact-subject IRSA role instead of accepted as an arbitrary
# protected tfvars ARN. This is derived from the upstream v3.2.2 policy with
# the unused IAM service-linked-role/server-certificate and Shield capabilities
# removed, and with mutations constrained to this VPC, account, region, and
# cluster ownership tag.
resource "aws_iam_role_policy" "load_balancer_controller" {
  name = "aws-load-balancer-controller"
  role = aws_iam_role.workload["ingress"].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadEc2AndElasticLoadBalancing"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeAddresses",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeCoipPools",
          "ec2:DescribeInstances",
          "ec2:DescribeInternetGateways",
          "ec2:DescribeIpamPools",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeRouteTables",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeTags",
          "ec2:DescribeVpcPeeringConnections",
          "ec2:DescribeVpcs",
          "ec2:GetCoipPoolUsage",
          "ec2:GetSecurityGroupsForVpc",
          "elasticloadbalancing:DescribeCapacityReservation",
          "elasticloadbalancing:DescribeListenerAttributes",
          "elasticloadbalancing:DescribeListenerCertificates",
          "elasticloadbalancing:DescribeListeners",
          "elasticloadbalancing:DescribeLoadBalancerAttributes",
          "elasticloadbalancing:DescribeLoadBalancers",
          "elasticloadbalancing:DescribeRules",
          "elasticloadbalancing:DescribeSSLPolicies",
          "elasticloadbalancing:DescribeTags",
          "elasticloadbalancing:DescribeTargetGroupAttributes",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetHealth",
          "elasticloadbalancing:DescribeTrustStores",
        ]
        Resource = "*"
      },
      {
        Sid    = "ReadCertificate"
        Effect = "Allow"
        Action = [
          "acm:DescribeCertificate",
          "acm:ListCertificates",
        ]
        Resource = "*"
      },
      {
        Sid    = "ReadAndAssociateModuleWafAcl"
        Effect = "Allow"
        Action = [
          "wafv2:AssociateWebACL",
          "wafv2:DisassociateWebACL",
          "wafv2:GetWebACL",
        ]
        Resource = aws_wafv2_web_acl.ingress.arn
      },
      {
        Sid    = "ReadAndAssociateWafOnOwnedLoadBalancers"
        Effect = "Allow"
        Action = [
          "wafv2:AssociateWebACL",
          "wafv2:DisassociateWebACL",
          "wafv2:GetWebACLForResource",
        ]
        Resource = "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/${var.cluster_name}-platform/*"
      },
      {
        Sid      = "CreateTaggedSecurityGroupInClusterVpc"
        Effect   = "Allow"
        Action   = ["ec2:CreateSecurityGroup"]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "ec2:Vpc" = aws_vpc.this.arn
          }
          StringEquals = {
            "aws:RequestTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid      = "TagSecurityGroupOnCreate"
        Effect   = "Allow"
        Action   = ["ec2:CreateTags"]
        Resource = "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:security-group/*"
        Condition = {
          StringEquals = {
            "ec2:CreateAction"                     = "CreateSecurityGroup"
            "aws:RequestTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "ManageOwnedSecurityGroupTags"
        Effect = "Allow"
        Action = [
          "ec2:CreateTags",
          "ec2:DeleteTags",
        ]
        Resource = "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:security-group/*"
        Condition = {
          ArnEquals = {
            "ec2:Vpc" = aws_vpc.this.arn
          }
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "ManageOwnedSecurityGroups"
        Effect = "Allow"
        Action = [
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:DeleteSecurityGroup",
          "ec2:RevokeSecurityGroupIngress",
        ]
        Resource = "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:security-group/*"
        Condition = {
          ArnEquals = {
            "ec2:Vpc" = aws_vpc.this.arn
          }
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "CreateTaggedLoadBalancersAndTargetGroups"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:CreateLoadBalancer",
          "elasticloadbalancing:CreateTargetGroup",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "TagOwnedLoadBalancersAndTargetGroups"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:AddTags",
          "elasticloadbalancing:RemoveTags",
        ]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/${var.cluster_name}-platform/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:targetgroup/*/*",
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "TagLoadBalancersAndTargetGroupsOnCreate"
        Effect = "Allow"
        Action = ["elasticloadbalancing:AddTags"]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/${var.cluster_name}-platform/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:targetgroup/*/*",
        ]
        Condition = {
          StringEquals = {
            "aws:RequestTag/elbv2.k8s.aws/cluster" = var.cluster_name
            "elasticloadbalancing:CreateAction" = [
              "CreateLoadBalancer",
              "CreateTargetGroup",
            ]
          }
        }
      },
      {
        Sid    = "ManageOwnedLoadBalancers"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DeleteLoadBalancer",
          "elasticloadbalancing:ModifyCapacityReservation",
          "elasticloadbalancing:ModifyIpPools",
          "elasticloadbalancing:ModifyLoadBalancerAttributes",
          "elasticloadbalancing:SetIpAddressType",
          "elasticloadbalancing:SetSecurityGroups",
          "elasticloadbalancing:SetSubnets",
          "elasticloadbalancing:SetWebAcl",
        ]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/${var.cluster_name}-platform/*",
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "ManageOwnedTargetGroups"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DeleteTargetGroup",
          "elasticloadbalancing:ModifyTargetGroup",
          "elasticloadbalancing:ModifyTargetGroupAttributes",
        ]
        Resource = "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:targetgroup/*/*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "ManageOwnedListenerAttributes"
        Effect = "Allow"
        Action = ["elasticloadbalancing:ModifyListenerAttributes"]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/app/*/*/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/net/*/*/*",
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "CreateListenersOnOwnedLoadBalancers"
        Effect = "Allow"
        Action = ["elasticloadbalancing:CreateListener"]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/${var.cluster_name}-platform/*",
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "CreateRulesOnOwnedListeners"
        Effect = "Allow"
        Action = ["elasticloadbalancing:CreateRule"]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/app/*/*/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/net/*/*/*",
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "ManageOwnedListenersAndRules"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:AddListenerCertificates",
          "elasticloadbalancing:AddTags",
          "elasticloadbalancing:DeleteListener",
          "elasticloadbalancing:DeleteRule",
          "elasticloadbalancing:ModifyListener",
          "elasticloadbalancing:ModifyRule",
          "elasticloadbalancing:RemoveListenerCertificates",
          "elasticloadbalancing:RemoveTags",
          "elasticloadbalancing:SetRulePriorities",
        ]
        Resource = [
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/app/*/*/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener/net/*/*/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener-rule/app/*/*/*",
          "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:listener-rule/net/*/*/*",
        ]
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
      {
        Sid    = "RegisterTargets"
        Effect = "Allow"
        Action = [
          "elasticloadbalancing:DeregisterTargets",
          "elasticloadbalancing:RegisterTargets",
        ]
        Resource = "arn:aws:elasticloadbalancing:${var.aws_region}:${data.aws_caller_identity.current.account_id}:targetgroup/*/*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name
          }
        }
      },
    ]
  })
}
