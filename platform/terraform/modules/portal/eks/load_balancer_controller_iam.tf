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
        # CreateSecurityGroup authorizes two resource legs: the VPC the group is
        # created in, and the (pre-create, unnamed) security-group resource itself.
        # The controller's backend-sg-provider does not tag-on-create (verified via
        # the decoded authorization context: no aws:RequestTag/* keys are present),
        # and the VPC leg exposes ec2:VpcID rather than the ec2:Vpc ARN key, so an
        # aws:RequestTag / ArnEquals ec2:Vpc condition never matches either leg and
        # every create was denied. Scope by resource ARN instead: groups may be
        # created only inside this cluster's VPC (the group id is unknowable before
        # creation, hence security-group/*). Cluster-ownership tagging and the
        # modify/delete gate remain enforced by TagSecurityGroupOnCreate and the
        # ManageOwnedSecurityGroup* statements below.
        Sid    = "CreateSecurityGroupInClusterVpc"
        Effect = "Allow"
        Action = ["ec2:CreateSecurityGroup"]
        Resource = [
          aws_vpc.this.arn,
          "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:security-group/*",
        ]
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

# IP-mode ALB targets are pod ENIs in the EKS-managed cluster security group.
# The controller must add an ingress rule there admitting its backend security
# group to the target ports, or every target times out. Its rule mutations are
# scoped to groups carrying the exact cluster ownership tag (ADR-044-R7), which
# EKS does not put on the group it creates, so tag it here.
resource "aws_ec2_tag" "cluster_security_group_lb_controller" {
  resource_id = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
  key         = "elbv2.k8s.aws/cluster"
  value       = var.cluster_name
}
