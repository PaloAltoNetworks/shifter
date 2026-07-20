variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Environment name (dev, prod, or proof)"
  type        = string
  validation {
    condition     = contains(["dev", "prod", "proof"], var.environment)
    error_message = "Environment must be 'dev', 'prod', or 'proof'."
  }
}

variable "github_org" {
  description = "GitHub organization"
  type        = string
  default     = "Brad-Edwards"
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "shifter"
}

# Get current AWS account ID
data "aws_caller_identity" "current" {}

# GitHub OIDC Provider
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1b511abead59c6ce207077c0bf0e0043b1382612"]

  tags = {
    Name    = "github-actions-oidc"
    Project = "shifter"
  }
}

# IAM Role for GitHub Actions
resource "aws_iam_role" "github_actions" {
  name = "github-actions-shifter-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
          }
        }
      }
    ]
  })

  tags = {
    Name        = "github-actions-shifter-${var.environment}"
    Project     = "shifter"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# Least-privilege base-image-pipeline role (#1656)
#
# The packer.yml base `build` job must not run under the broad github_actions
# deploy role above: that role legitimately passes portal EC2, ECS, Lambda,
# RDS-monitoring, and every range role to AWS services, so it cannot
# simultaneously prove that a base-image verification instance may receive ONLY
# the range instance role. This dedicated principal IS the IAM boundary the
# workflow's inline ref gate is not:
#
#   * OIDC trust is pinned to the EXACT protected-branch subjects
#     (refs/heads/dev, refs/heads/main) - never repo:...:* - so a pull-request
#     or feature-branch job cannot assume it even if it can dispatch the
#     workflow.
#   * iam:PassRole is scoped to the EXACT env range role
#     (shifter-${var.environment}-range-range-instance) passed to
#     ec2.amazonaws.com and nothing else, so the fresh-boot verifier can launch
#     a range-profile instance while the role cannot exfiltrate a more-privileged
#     profile (AWS warns role tags / profile-name checks are not a PassRole
#     boundary).
#   * EC2 is the amazon-ebs builder + verifier + always() cleanup action set;
#     SSM is the verifier (DescribeInstanceInformation / SendCommand /
#     GetCommandInvocation) plus publication of the /shifter/ami/* base pointers
#     only. No IAM mutation, Secrets Manager, arbitrary Parameter Store, or
#     scenario-artifact access.
#
# The exact-subject and exact-range-role invariants are enforced by
# scripts/check_tf_iam_role_naming (ADR-004-R22). Binding design note:
# docs/architecture/packer-base-build-privilege-boundary-preflight-1656.md.
# ------------------------------------------------------------------------------
resource "aws_iam_role" "github_actions_image" {
  name = "github-actions-shifter-${var.environment}-image"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            # EXACT protected-branch subjects only (never repo:...:*). The base
            # build runs from dev|main (the workflow's inline ref gate); a
            # feature-branch or pull-request subject receives no AWS role.
            "token.actions.githubusercontent.com:sub" = [
              "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/dev",
              "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main"
            ]
          }
        }
      }
    ]
  })

  tags = {
    Name        = "github-actions-shifter-${var.environment}-image"
    Project     = "shifter"
    Environment = var.environment
  }
}

# Packer amazon-ebs AMI/instance/snapshot operations cannot be meaningfully
# ARN-scoped, so the EC2 statement keeps Resource "*" and constrains by action to
# the documented builder+verifier+cleanup set (never ec2:*). The PassRole and SSM
# statements ARE tightly scoped. The checkov skips below cover only unavoidable
# Packer EC2 findings; the least-privilege boundary is the action list plus the
# exact PassRole/SSM-publish resources (#1656).
resource "aws_iam_role_policy" "image_pipeline" {
  # checkov:skip=CKV_AWS_355:Packer EC2 build/verify actions are not ARN-scopable; scoped by action, not ec2:*. Risk accepted, see #1656.
  # checkov:skip=CKV_AWS_290:EC2 build/verify needs Resource=*; PassRole is the exact range role and SSM publish is /shifter/ami/* PutParameter only. See #1656.
  # checkov:skip=CKV_AWS_287:ec2:GetPasswordData is required for Packer Windows base builds (WinRM admin password) and is not ARN-scopable; the role grants no other credential-exposure action. Risk accepted, see #1656.
  name = "shifter-${var.environment}-image-pipeline"
  role = aws_iam_role.github_actions_image.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # amazon-ebs builder + fresh-boot verifier + always() cleanup. RebootInstances
        # covers the verifier's reboot-survival check (base-image-verify.sh).
        Sid    = "Ec2ImageBuildAndVerify"
        Effect = "Allow"
        Action = [
          "ec2:AttachVolume",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:CopyImage",
          "ec2:CreateImage",
          "ec2:CreateKeyPair",
          "ec2:CreateSecurityGroup",
          "ec2:CreateSnapshot",
          "ec2:CreateTags",
          "ec2:CreateVolume",
          "ec2:DeleteKeyPair",
          "ec2:DeleteSecurityGroup",
          "ec2:DeleteSnapshot",
          "ec2:DeleteVolume",
          "ec2:DeregisterImage",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImageAttribute",
          "ec2:DescribeImages",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeKeyPairs",
          "ec2:DescribeRegions",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSnapshots",
          "ec2:DescribeSubnets",
          "ec2:DescribeTags",
          "ec2:DescribeVolumes",
          "ec2:DescribeVpcs",
          "ec2:DetachVolume",
          "ec2:GetPasswordData",
          "ec2:ModifyImageAttribute",
          "ec2:ModifyInstanceAttribute",
          "ec2:ModifySnapshotAttribute",
          "ec2:RebootInstances",
          "ec2:RegisterImage",
          "ec2:RunInstances",
          "ec2:StopInstances",
          "ec2:TerminateInstances"
        ]
        Resource = "*"
      },
      {
        # The fresh-boot verifier launches a candidate with the range instance
        # profile (base-image-verify.sh --iam-instance-profile). This role may
        # pass ONLY the exact env range role to EC2 - not shifter-*, not
        # *-range-instance, not any other role - so a tampered verify profile
        # cannot exfiltrate a more-privileged role.
        Sid      = "PassRangeInstanceRoleToEc2Only"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-range-range-instance"
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ec2.amazonaws.com"
          }
        }
      },
      {
        # Verifier SSM checks: confirm the candidate registers with SSM and can
        # resolve DNS via Run Command. List actions are not ARN-scopable.
        Sid    = "SsmVerifyInstanceInformation"
        Effect = "Allow"
        Action = [
          "ssm:DescribeInstanceInformation",
          "ssm:GetCommandInvocation"
        ]
        Resource = "*"
      },
      {
        # SendCommand scoped to instances in this account and the two documents
        # the verifier invokes (Linux + Windows DNS resolution probe).
        Sid    = "SsmVerifyRunCommand"
        Effect = "Allow"
        Action = ["ssm:SendCommand"]
        Resource = [
          "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/*",
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript",
          "arn:aws:ssm:${var.aws_region}::document/AWS-RunPowerShellScript"
        ]
      },
      {
        # Publish the validated base AMI id to the runtime pointer. Write-only
        # (the build only ever put-parameters /shifter/ami/<type>; it never reads
        # a parameter), scoped to the /shifter/ami/* namespace - not arbitrary
        # Parameter Store, and no read grant that would trip credential-exposure.
        Sid      = "PublishBaseAmiPointer"
        Effect   = "Allow"
        Action   = ["ssm:PutParameter"]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/shifter/ami/*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Managed IAM Policies
#
# Consolidated by AWS service category (#254) to stay under AWS's hard limit of
# 10 managed policies per role. Five domain policies (compute, networking, data,
# security, management) leave headroom for future growth: a new service should
# extend an existing category, not add an eleventh attachment. The
# `check_tf_iam_role_naming` gate enforces the attachment cap. Consolidation is a
# structural move of existing statements; no permissions are broadened.
# ------------------------------------------------------------------------------

# Permissions boundary applied to every CI-created shifter-* role (#253).
# Standalone policy referenced by the security policy's iam:CreateRole condition;
# intentionally NOT attached to the github_actions role.
resource "aws_iam_policy" "ci_role_permissions_boundary" {
  # This is a permissions BOUNDARY, not a principal grant. A boundary caps the MAX permissions of
  # the CI-created service roles it bounds; effective perms are the intersection of each role's own
  # identity policy AND this boundary. The Allow*/* sets the ceiling to "anything", which the
  # DenyIamEscalation below carves IAM out of, yielding "all except IAM escalation". Without the
  # Allow* the boundary permits nothing and cripples every bounded role (e.g. firehose:PutRecord on
  # the log-shipping role). The wildcard-policy checks below assume a grant policy and do not apply
  # to boundary semantics. Risk accepted, see #44.
  # checkov:skip=CKV_AWS_286:Boundary ceiling, not a principal grant; iam:* is denied so no escalation.
  # checkov:skip=CKV_AWS_287:Boundary, not a grant; it only caps effective perms, never exposes creds.
  # checkov:skip=CKV_AWS_288:Boundary, not a grant - no data-exfil risk; it only caps, never grants.
  # checkov:skip=CKV_AWS_62:Boundary ceiling, not an administrative grant to any principal.
  # checkov:skip=CKV_AWS_63:Action="*" is required for a boundary to permit non-IAM service actions.
  # checkov:skip=CKV2_AWS_40:DenyIamEscalation removes IAM; the boundary does not allow full IAM.
  name = "shifter-${var.environment}-ci-role-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # A permissions boundary must explicitly ALLOW an action for a bounded role to use it
        # (effective = identity policy ∩ boundary). This Allow* sets the ceiling to "anything",
        # which the DenyIamEscalation below then carves IAM back out of, yielding the intended
        # "all except IAM escalation" cap. It grants nothing on its own.
        Sid      = "AllowAllExceptDenied"
        Effect   = "Allow"
        Action   = "*"
        Resource = "*"
      },
      {
        # Deny every IAM action (the anti-escalation cap, #253) EXCEPT a scoped
        # iam:PassRole to the AWS services the platform legitimately hands roles
        # to at runtime. Without this carve-out a bounded, CI-created runtime role
        # (e.g. the portal EC2 role) cannot pass the provisioner's ECS execution
        # role on ecs:RunTask, so no range can launch (issue #1452). The condition
        # only relaxes the deny for iam:PassRole calls whose iam:PassedToService is
        # one of these services; every other iam:* call (CreateRole, AttachPolicy,
        # PutRolePolicy, PassRole to any other service, and — because those calls
        # do not populate iam:PassedToService, so StringNotEquals matches on the
        # absent key — all non-PassRole IAM mutation) stays denied. The service
        # list mirrors the deploy role's own IAMPassRole grant above.
        Sid    = "DenyIamEscalation"
        Effect = "Deny"
        Action = "iam:*"
        # Carve the exact runtime-managed role/profile namespaces OUT of this
        # blanket IAM deny so the provisioner can create them at range provision
        # time. Each CreateRole grant requires THIS boundary and neither runtime
        # path can strip it. The explicit tamper denies below keep that cap in
        # place as defense-in-depth. These are namespace exceptions to a deny,
        # not grants; the provisioner identity policy remains the allow boundary.
        NotResource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-polaris-agent",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-vpn-gateway",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway"
        ]
        Condition = {
          StringNotEquals = {
            "iam:PassedToService" = [
              "ec2.amazonaws.com",
              "ecs-tasks.amazonaws.com",
              "lambda.amazonaws.com",
              "monitoring.rds.amazonaws.com",
              "vpc-flow-logs.amazonaws.com",
              "firehose.amazonaws.com",
              "logs.amazonaws.com",
              "bedrock.amazonaws.com",
              "scheduler.amazonaws.com"
            ]
          }
        }
      },
      {
        # Defense-in-depth for the polaris-agent namespace carve-out above. The
        # per-range polaris agent role (#1377) is created by the provisioner with
        # THIS boundary attached (enforced by the provisioner identity policy's
        # iam:PermissionsBoundary condition), so its effective permissions stay
        # capped even if its inline policy were broad. Explicitly deny stripping
        # or swapping that boundary on the agent roles so the cap can never be
        # removed after creation.
        Sid    = "DenyPolarisAgentBoundaryTamper"
        Effect = "Deny"
        Action = [
          "iam:PutRolePermissionsBoundary",
          "iam:DeleteRolePermissionsBoundary"
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-polaris-agent"
      },
      {
        # The VPN role and instance-profile namespaces are excluded from the
        # blanket IAM deny only so the provisioner can manage request-owned
        # gateways. Keep the role's mandatory boundary immutable after create.
        Sid    = "DenyVpnGatewayBoundaryTamper"
        Effect = "Deny"
        Action = [
          "iam:PutRolePermissionsBoundary",
          "iam:DeleteRolePermissionsBoundary"
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
      }
    ]
  })
}

# Compute: EC2, Auto Scaling, Lambda, ECS
# checkov:skip=CKV_AWS_355:CI/CD requires broad compute permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad compute permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad compute permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad compute permissions for infrastructure management. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "compute" {
  # checkov:skip=CKV_AWS_287:CI/CD requires broad compute permissions for infrastructure management. Risk accepted, see #44
  name = "shifter-${var.environment}-compute"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # TODO: Scope down EC2 permissions - see GitHub issue for audit
      {
        Sid      = "EC2"
        Effect   = "Allow"
        Action   = ["ec2:*"]
        Resource = "*"
      },
      {
        # Packer's amazon-ebs SSM communicator (ssh_interface = "session_manager",
        # used by the no-inbound techvault / polaris-vm scenario bakes) opens an
        # SSH-over-SSM tunnel to the EC2 builder via the AWS-StartSSHSession
        # document. The management policy's SSMRunCommand grant covers SendCommand
        # but not StartSession, so the scenario bakes fail with AccessDenied
        # without this. Lives in the compute policy (it targets EC2 build hosts)
        # to keep the management managed-policy under the 6144-char limit (#254).
        Sid    = "SSMSessionManagerForPackerBuilds"
        Effect = "Allow"
        Action = [
          "ssm:StartSession",
          "ssm:TerminateSession",
          "ssm:ResumeSession"
        ]
        Resource = [
          "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:instance/*",
          "arn:aws:ssm:${var.aws_region}::document/AWS-StartSSHSession",
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:session/*"
        ]
      },
      {
        Sid    = "AutoScaling"
        Effect = "Allow"
        Action = [
          "autoscaling:CreateAutoScalingGroup",
          "autoscaling:DeleteAutoScalingGroup",
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:UpdateAutoScalingGroup",
          "autoscaling:CreateLaunchConfiguration",
          "autoscaling:DeleteLaunchConfiguration",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:CreateOrUpdateTags",
          "autoscaling:DeleteTags",
          "autoscaling:DescribeTags",
          "autoscaling:PutScalingPolicy",
          "autoscaling:DeletePolicy",
          "autoscaling:DescribePolicies",
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup",
          "autoscaling:StartInstanceRefresh",
          "autoscaling:DescribeInstanceRefreshes",
          "autoscaling:DescribeScalingActivities",
          # Lifecycle hooks (launch + termination-drain) managed by
          # modules/portal/ec2. Describe is needed at plan/refresh time,
          # Put/Delete at apply time (including destroying hooks left in
          # state when enable_autoscaling is toggled off, as in dev).
          "autoscaling:DescribeLifecycleHooks",
          "autoscaling:PutLifecycleHook",
          "autoscaling:DeleteLifecycleHook",
          # Warm pool, managed by the same module's dynamic "warm_pool"
          # block when asg_warm_pool_min_size > 0.
          "autoscaling:DescribeWarmPool",
          "autoscaling:PutWarmPool",
          "autoscaling:DeleteWarmPool"
        ]
        Resource = "*"
      },
      {
        Sid    = "ApplicationAutoScaling"
        Effect = "Allow"
        Action = [
          "application-autoscaling:RegisterScalableTarget",
          "application-autoscaling:DeregisterScalableTarget",
          "application-autoscaling:DescribeScalableTargets",
          "application-autoscaling:PutScalingPolicy",
          "application-autoscaling:DeleteScalingPolicy",
          "application-autoscaling:DescribeScalingPolicies",
          "application-autoscaling:DescribeScalingActivities",
          "application-autoscaling:ListTagsForResource",
          "application-autoscaling:TagResource",
          "application-autoscaling:UntagResource"
        ]
        Resource = "*"
      },
      {
        Sid    = "Lambda"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:ListVersionsByFunction",
          "lambda:PublishVersion",
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:GetPolicy",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:ListTags",
          # Configuring Secrets Manager rotation (aws_secretsmanager_secret_rotation
          # for the Redis AUTH secret, #159) requires the caller to hold
          # lambda:InvokeFunction on the rotation function.
          "lambda:InvokeFunction"
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:*"
      },
      {
        Sid    = "LambdaLayers"
        Effect = "Allow"
        Action = [
          "lambda:PublishLayerVersion",
          "lambda:GetLayerVersion",
          "lambda:DeleteLayerVersion",
          "lambda:ListLayerVersions"
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:layer:*"
      },
      {
        Sid    = "ECS"
        Effect = "Allow"
        Action = [
          "ecs:*"
        ]
        Resource = "*"
      },
      {
        # Cloud Map service discovery (private DNS namespace + services) backing
        # ECS services. Namespace creation is async, so GetOperation is required
        # for Terraform to poll. Actions are not reliably ARN-addressable, so the
        # statement scopes by action and keeps Resource "*".
        Sid    = "ServiceDiscovery"
        Effect = "Allow"
        Action = [
          "servicediscovery:GetNamespace",
          "servicediscovery:ListNamespaces",
          "servicediscovery:CreatePrivateDnsNamespace",
          "servicediscovery:DeleteNamespace",
          "servicediscovery:GetService",
          "servicediscovery:ListServices",
          "servicediscovery:CreateService",
          "servicediscovery:UpdateService",
          "servicediscovery:DeleteService",
          "servicediscovery:GetOperation",
          "servicediscovery:ListTagsForResource",
          "servicediscovery:TagResource",
          "servicediscovery:UntagResource"
        ]
        Resource = "*"
      },
      {
        # Bedrock model-invocation logging configuration (account-level).
        Sid    = "Bedrock"
        Effect = "Allow"
        Action = [
          "bedrock:GetModelInvocationLoggingConfiguration",
          "bedrock:PutModelInvocationLoggingConfiguration",
          "bedrock:DeleteModelInvocationLoggingConfiguration"
        ]
        Resource = "*"
      },
      {
        # EventBridge Scheduler backing the Cognito client-secret rotation
        # reminder (portal cognito module, created when alarm_email is set so
        # enable_rotation_reminder is true). Scoped to the project/env schedule
        # name prefixes in the default schedule group.
        Sid    = "Scheduler"
        Effect = "Allow"
        Action = [
          "scheduler:CreateSchedule",
          "scheduler:GetSchedule",
          "scheduler:UpdateSchedule",
          "scheduler:DeleteSchedule",
          "scheduler:ListSchedules",
          "scheduler:TagResource",
          "scheduler:UntagResource",
          "scheduler:ListTagsForResource"
        ]
        Resource = [
          "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/default/shifter-*",
          "arn:aws:scheduler:${var.aws_region}:${data.aws_caller_identity.current.account_id}:schedule/default/${var.environment}-*"
        ]
      }
    ]
  })
}

# Networking: VPC, ELB, ACM, WAFv2, Network Firewall
# checkov:skip=CKV_AWS_355:CI/CD requires broad networking permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad networking permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad networking permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad networking permissions for infrastructure management. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "networking" {
  name = "shifter-${var.environment}-networking"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "VPC"
        Effect = "Allow"
        Action = [
          "ec2:*Vpc*",
          "ec2:*Subnet*",
          "ec2:*RouteTable*",
          "ec2:*Route",
          "ec2:*InternetGateway*",
          "ec2:*NatGateway*",
          "ec2:*Address*",
          "ec2:*SecurityGroup*",
          "ec2:*Tags",
          "ec2:Describe*",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "ec2:CreateFlowLogs",
          "ec2:DeleteFlowLogs",
          "ec2:DescribeFlowLogs"
        ]
        Resource = "*"
      },
      {
        Sid      = "ELB"
        Effect   = "Allow"
        Action   = ["elasticloadbalancing:*"]
        Resource = "*"
      },
      {
        Sid      = "ACM"
        Effect   = "Allow"
        Action   = ["acm:*"]
        Resource = "*"
      },
      {
        Sid    = "WAFv2"
        Effect = "Allow"
        Action = [
          "wafv2:CreateWebACL",
          "wafv2:DeleteWebACL",
          "wafv2:GetWebACL",
          "wafv2:UpdateWebACL",
          "wafv2:ListWebACLs",
          "wafv2:AssociateWebACL",
          "wafv2:DisassociateWebACL",
          "wafv2:GetWebACLForResource",
          "wafv2:ListResourcesForWebACL",
          "wafv2:ListTagsForResource",
          "wafv2:TagResource",
          "wafv2:UntagResource",
          "wafv2:DescribeManagedRuleGroup",
          "wafv2:ListAvailableManagedRuleGroups",
          "wafv2:GetLoggingConfiguration",
          "wafv2:PutLoggingConfiguration",
          "wafv2:DeleteLoggingConfiguration",
          "wafv2:ListLoggingConfigurations"
        ]
        Resource = "*"
      },
      {
        Sid    = "NetworkFirewall"
        Effect = "Allow"
        Action = [
          "network-firewall:CreateFirewall",
          "network-firewall:DeleteFirewall",
          "network-firewall:DescribeFirewall",
          "network-firewall:UpdateFirewallDeleteProtection",
          "network-firewall:UpdateFirewallDescription",
          "network-firewall:UpdateFirewallPolicy",
          "network-firewall:UpdateFirewallPolicyChangeProtection",
          "network-firewall:UpdateSubnetChangeProtection",
          "network-firewall:AssociateFirewallPolicy",
          "network-firewall:DisassociateSubnets",
          "network-firewall:AssociateSubnets",
          "network-firewall:CreateFirewallPolicy",
          "network-firewall:DeleteFirewallPolicy",
          "network-firewall:DescribeFirewallPolicy",
          "network-firewall:UpdateFirewallPolicy",
          "network-firewall:CreateRuleGroup",
          "network-firewall:DeleteRuleGroup",
          "network-firewall:DescribeRuleGroup",
          "network-firewall:UpdateRuleGroup",
          "network-firewall:ListFirewalls",
          "network-firewall:ListFirewallPolicies",
          "network-firewall:ListRuleGroups",
          "network-firewall:TagResource",
          "network-firewall:UntagResource",
          "network-firewall:ListTagsForResource",
          "network-firewall:DescribeLoggingConfiguration",
          "network-firewall:UpdateLoggingConfiguration"
        ]
        Resource = "*"
      },
      {
        # Route 53 Resolver DNS Firewall + query logging for the range VPC
        # egress controls (#1171 zero-egress range, #1172 close DNS exfil,
        # modules/range/vpc/dns_resolver.tf). None of these APIs support
        # resource-level scoping, so the statement uses Resource "*".
        Sid    = "Route53ResolverDNSFirewall"
        Effect = "Allow"
        Action = [
          "route53resolver:CreateFirewallDomainList",
          "route53resolver:DeleteFirewallDomainList",
          "route53resolver:GetFirewallDomainList",
          "route53resolver:ListFirewallDomainLists",
          "route53resolver:UpdateFirewallDomains",
          "route53resolver:ListFirewallDomains",
          "route53resolver:ImportFirewallDomains",
          "route53resolver:CreateFirewallRuleGroup",
          "route53resolver:DeleteFirewallRuleGroup",
          "route53resolver:GetFirewallRuleGroup",
          "route53resolver:ListFirewallRuleGroups",
          "route53resolver:CreateFirewallRule",
          "route53resolver:DeleteFirewallRule",
          "route53resolver:UpdateFirewallRule",
          "route53resolver:ListFirewallRules",
          "route53resolver:AssociateFirewallRuleGroup",
          "route53resolver:DisassociateFirewallRuleGroup",
          "route53resolver:GetFirewallRuleGroupAssociation",
          "route53resolver:ListFirewallRuleGroupAssociations",
          "route53resolver:UpdateFirewallRuleGroupAssociation",
          "route53resolver:GetFirewallConfig",
          "route53resolver:UpdateFirewallConfig",
          "route53resolver:ListFirewallConfigs",
          "route53resolver:CreateResolverQueryLogConfig",
          "route53resolver:DeleteResolverQueryLogConfig",
          "route53resolver:GetResolverQueryLogConfig",
          "route53resolver:ListResolverQueryLogConfigs",
          "route53resolver:AssociateResolverQueryLogConfig",
          "route53resolver:DisassociateResolverQueryLogConfig",
          "route53resolver:GetResolverQueryLogConfigAssociation",
          "route53resolver:ListResolverQueryLogConfigAssociations",
          "route53resolver:TagResource",
          "route53resolver:UntagResource",
          "route53resolver:ListTagsForResource"
        ]
        Resource = "*"
      },
      {
        # Route53 hosted zones. Cloud Map / Service Discovery private DNS
        # namespaces (module.guacamole.aws_service_discovery_private_dns_namespace)
        # create a backing private hosted zone, so the CI role needs route53
        # hosted-zone actions in addition to servicediscovery:*. Only surfaces on
        # a from-zero standup: established accounts already have the namespace, so
        # no CreateHostedZone call is made (#1425). CreateHostedZone has no
        # resource-level scoping, so Resource = "*".
        Sid    = "Route53HostedZones"
        Effect = "Allow"
        Action = [
          "route53:CreateHostedZone",
          "route53:GetHostedZone",
          "route53:GetHostedZoneCount",
          "route53:ListHostedZones",
          "route53:ListHostedZonesByName",
          "route53:DeleteHostedZone",
          "route53:UpdateHostedZoneComment",
          "route53:AssociateVPCWithHostedZone",
          "route53:DisassociateVPCFromHostedZone",
          "route53:ChangeResourceRecordSets",
          "route53:ListResourceRecordSets",
          "route53:GetChange",
          "route53:ListTagsForResource",
          "route53:ChangeTagsForResource"
        ]
        Resource = "*"
      }
    ]
  })
}

# Data: ECR, S3, DynamoDB, Pulumi state, RDS, ElastiCache
# checkov:skip=CKV_AWS_355:CI/CD requires broad data-store permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad data-store permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad data-store permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad data-store permissions for infrastructure management. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "data" {
  name = "shifter-${var.environment}-data"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECR"
        Effect   = "Allow"
        Action   = ["ecr:*"]
        Resource = "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/shifter-*"
      },
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "S3State"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          # Prod state bucket (shifter-infra-*) and per-environment state
          # buckets (shifter-dev-infra-*, shifter-proof-infra-*, ...).
          "arn:aws:s3:::shifter-infra-*",
          "arn:aws:s3:::shifter-infra-*/*",
          "arn:aws:s3:::shifter-*-infra-*",
          "arn:aws:s3:::shifter-*-infra-*/*"
        ]
      },
      {
        Sid    = "S3BakeBucketsRead"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject"
        ]
        # Scenario bake buckets (e.g. shifter-polaris-bake-<account>). The
        # polaris bake verifies the operator-uploaded build tarball exists
        # before standing up a golden range. Read-only: the operator uploads
        # the tarball out of band and the range instance role (granted in
        # scripts/polaris-aws-range) does the actual download.
        Resource = [
          "arn:aws:s3:::shifter-*-bake-*",
          "arn:aws:s3:::shifter-*-bake-*/*"
        ]
      },
      {
        Sid    = "S3UserStorage"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::shifter-user-storage-*",
          "arn:aws:s3:::shifter-*-user-storage-*"
        ]
      },
      {
        Sid    = "S3PortalBuckets"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          # Portal-owned buckets (logs, ALB access logs, etc.) named {env}-portal-*.
          "arn:aws:s3:::*-portal-*",
          "arn:aws:s3:::*-portal-*/*"
        ]
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/shifter-terraform-*"
      },
      {
        Sid    = "PulumiStateS3"
        Effect = "Allow"
        Action = [
          "s3:*"
        ]
        Resource = [
          # Bucket names carry an account-id suffix (e.g. proof-range-pulumi-state-<acct>),
          # so match the prefix with a trailing wildcard.
          "arn:aws:s3:::*-range-pulumi-state*",
          "arn:aws:s3:::*-range-pulumi-state*/*"
        ]
      },
      {
        Sid    = "PulumiStateDynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable",
          "dynamodb:DeleteTable",
          "dynamodb:DescribeTable",
          "dynamodb:UpdateTable",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:UpdateTimeToLive",
          "dynamodb:ListTagsOfResource",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:UpdateContinuousBackups"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/*-range-pulumi-locks"
      },
      {
        Sid    = "RDS"
        Effect = "Allow"
        Action = [
          "rds:CreateDBInstance",
          "rds:DeleteDBInstance",
          "rds:DescribeDBInstances",
          "rds:ModifyDBInstance",
          "rds:RebootDBInstance",
          "rds:StartDBInstance",
          "rds:StopDBInstance",
          "rds:CreateDBSubnetGroup",
          "rds:DeleteDBSubnetGroup",
          "rds:DescribeDBSubnetGroups",
          "rds:ModifyDBSubnetGroup",
          "rds:CreateDBParameterGroup",
          "rds:DeleteDBParameterGroup",
          "rds:DescribeDBParameterGroups",
          "rds:ModifyDBParameterGroup",
          "rds:DescribeDBParameters",
          "rds:AddTagsToResource",
          "rds:RemoveTagsFromResource",
          "rds:ListTagsForResource",
          "rds:DescribeDBEngineVersions",
          "rds:DescribeOrderableDBInstanceOptions",
          "rds:CreateEventSubscription",
          "rds:DeleteEventSubscription",
          "rds:ModifyEventSubscription",
          "rds:DescribeEventSubscriptions",
          "rds:AddSourceIdentifierToSubscription",
          "rds:RemoveSourceIdentifierFromSubscription"
        ]
        Resource = "*"
      },
      {
        # ElastiCache (Redis) replication groups, clusters, and subnet groups for
        # the portal. Describe/tag actions are not ARN-addressable, so the
        # statement scopes by action and keeps Resource "*".
        Sid    = "ElastiCache"
        Effect = "Allow"
        Action = [
          "elasticache:DescribeCacheClusters",
          "elasticache:DescribeReplicationGroups",
          "elasticache:DescribeCacheSubnetGroups",
          "elasticache:CreateCacheCluster",
          "elasticache:DeleteCacheCluster",
          "elasticache:ModifyCacheCluster",
          "elasticache:CreateReplicationGroup",
          "elasticache:DeleteReplicationGroup",
          "elasticache:ModifyReplicationGroup",
          "elasticache:CreateCacheSubnetGroup",
          "elasticache:DeleteCacheSubnetGroup",
          "elasticache:ModifyCacheSubnetGroup",
          "elasticache:ListTagsForResource",
          "elasticache:AddTagsToResource",
          "elasticache:RemoveTagsFromResource"
        ]
        Resource = "*"
      }
    ]
  })
}

# Security: IAM (scoped), Secrets Manager, KMS
# checkov:skip=CKV_AWS_355:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
# IAM statements stay restricted to shifter-* naming after #253 role standardization.
resource "aws_iam_policy" "security" {
  name = "shifter-${var.environment}-security"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAMCreateRoleWithBoundary"
        Effect = "Allow"
        Action = ["iam:CreateRole"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.environment}-*"
        ]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.ci_role_permissions_boundary.arn
          }
        }
      },
      {
        Sid    = "IAMRoles"
        Effect = "Allow"
        Action = [
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:UpdateRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:PutRolePolicy",
          "iam:GetRolePolicy",
          "iam:DeleteRolePolicy"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.environment}-*"
        ]
      },
      {
        Sid    = "IAMAttachManagedPolicy"
        Effect = "Allow"
        Action = [
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.environment}-*"
        ]
        Condition = {
          ArnEquals = {
            "iam:PolicyArn" = [
              "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
              "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
              "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
              "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
            ]
          }
        }
      },
      {
        # Attach/detach account-owned customer-managed policies (e.g. the
        # ${env}-portal-pulumi-* managed policies the provisioner roles use).
        # Scoped to roles and policies under the project/env name prefixes so
        # this cannot attach arbitrary AWS-managed policies (that path stays
        # gated by IAMAttachManagedPolicy's allow-list above).
        Sid    = "IAMAttachCustomerManagedPolicy"
        Effect = "Allow"
        Action = [
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.environment}-*"
        ]
        Condition = {
          ArnLike = {
            "iam:PolicyArn" = [
              "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shifter-*",
              "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${var.environment}-*"
            ]
          }
        }
      },
      {
        Sid    = "IAMInstanceProfiles"
        Effect = "Allow"
        Action = [
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:UntagInstanceProfile"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/${var.environment}-*"
        ]
      },
      {
        Sid    = "IAMPassRole"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.environment}-*"
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = [
              "ec2.amazonaws.com",
              "ecs-tasks.amazonaws.com",
              "lambda.amazonaws.com",
              "monitoring.rds.amazonaws.com",
              "vpc-flow-logs.amazonaws.com",
              "firehose.amazonaws.com",
              "logs.amazonaws.com",
              "bedrock.amazonaws.com",
              "scheduler.amazonaws.com"
            ]
          }
        }
      },
      {
        # RDS enhanced-monitoring role pass. RDS ModifyDBInstance does NOT populate the
        # iam:PassedToService context key, so the conditional IAMPassRole statement above
        # never matches and enabling enhanced monitoring fails with PassRole AccessDenied.
        # Allow passing the enhanced-monitoring roles without that condition, but scope the
        # resource tightly to *-rds-enhanced-monitoring roles. Their trust policy only permits
        # monitoring.rds.amazonaws.com, so an unconditional pass of just these roles is safe.
        Sid    = "IAMPassRoleRdsMonitoring"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*-rds-enhanced-monitoring",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.environment}-*-rds-enhanced-monitoring"
        ]
      },
      {
        Sid      = "IAMServiceLinkedRoles"
        Effect   = "Allow"
        Action   = ["iam:CreateServiceLinkedRole"]
        Resource = "arn:aws:iam::*:role/aws-service-role/*"
      },
      {
        Sid    = "IAMManagedPolicies"
        Effect = "Allow"
        Action = [
          "iam:CreatePolicy",
          "iam:DeletePolicy",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:ListPolicyVersions",
          "iam:CreatePolicyVersion",
          "iam:DeletePolicyVersion",
          "iam:ListEntitiesForPolicy",
          "iam:TagPolicy",
          "iam:UntagPolicy"
        ]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${var.environment}-*"
        ]
      },
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecret",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:PutResourcePolicy",
          "secretsmanager:DeleteResourcePolicy",
          # Enable/trigger managed rotation for the Redis AUTH secret
          # (modules/portal/redis aws_secretsmanager_secret_rotation, #159).
          "secretsmanager:RotateSecret",
          "secretsmanager:CancelRotateSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-*"
      },
      {
        Sid      = "SecretsManagerRandom"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetRandomPassword"]
        Resource = "*"
      },
      {
        Sid    = "KMS"
        Effect = "Allow"
        Action = [
          "kms:CreateKey",
          "kms:DescribeKey",
          "kms:CreateAlias",
          "kms:DeleteAlias",
          "kms:ListAliases",
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ScheduleKeyDeletion",
          "kms:GetKeyPolicy",
          "kms:PutKeyPolicy",
          "kms:EnableKeyRotation",
          "kms:GetKeyRotationStatus",
          "kms:ListResourceTags",
          # Grant management: ElastiCache (and other AWS services) create a
          # grant on the customer CMK when a resource with at-rest encryption
          # is created (e.g. the portal Redis replication group). CreateGrant
          # is also needed by the apply that provisions those resources.
          "kms:CreateGrant",
          "kms:ListGrants",
          "kms:RevokeGrant",
          "kms:ReEncrypt*",
          "kms:GenerateDataKeyWithoutPlaintext"
        ]
        Resource = "*"
      }
    ]
  })
}

# Management: SSM, Cognito, CloudWatch (Logs + Alarms), SNS, EventBridge
# checkov:skip=CKV_AWS_355:CI/CD requires broad SSM/Cognito/observability permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad SSM/Cognito/observability permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad SSM/Cognito/observability permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad SSM/Cognito/observability permissions. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "management" {
  # checkov:skip=CKV_AWS_287:CI/CD requires broad SSM/Cognito/observability permissions. Risk accepted, see #44
  name = "shifter-${var.environment}-management"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMRunCommand"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations",
          "ssm:DescribeInstanceInformation",
          # DescribeParameters is a list action that does not support
          # resource-level scoping; it must be granted on "*".
          "ssm:DescribeParameters"
        ]
        Resource = "*"
      },
      {
        Sid    = "SSMParameterStore"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:DeleteParameter",
          "ssm:DescribeParameters",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource"
        ]
        Resource = [
          # All shifter-namespaced parameters: range DC config, AMI IDs, and
          # per-environment portal parameters (/shifter/<env>/portal/*).
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/shifter/*"
        ]
      },
      {
        Sid    = "SSMPublicServiceParametersRead"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        # AWS-owned PUBLIC parameters (no account in the ARN) used to resolve
        # current base AMIs at build time - e.g. the Canonical Ubuntu and
        # Amazon Linux AMI-ID parameters the scenario bakes (techvault /
        # polaris golden ranges) read. Read-only; scoped to /aws/service/*.
        Resource = [
          "arn:aws:ssm:${var.aws_region}::parameter/aws/service/*"
        ]
      },
      {
        Sid      = "Cognito"
        Effect   = "Allow"
        Action   = ["cognito-idp:*"]
        Resource = "*"
      },
      {
        # CloudWatch Logs (log groups, streams, metric/subscription filters) for
        # the portal/range/firehose log pipelines. Action set is scoped to the
        # lifecycle Terraform exercises for these resources; log data is
        # operational, not secret. Describe/List/Put actions do not support
        # resource-level constraints, so Resource stays "*".
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy",
          "logs:CreateLogStream",
          "logs:DeleteLogStream",
          "logs:DescribeLogStreams",
          "logs:PutMetricFilter",
          "logs:DeleteMetricFilter",
          "logs:DescribeMetricFilters",
          "logs:PutSubscriptionFilter",
          "logs:DeleteSubscriptionFilter",
          "logs:DescribeSubscriptionFilters",
          "logs:AssociateKmsKey",
          "logs:DisassociateKmsKey",
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
          "logs:PutResourcePolicy",
          "logs:DeleteResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:ListLogDeliveries",
          "logs:GetLogDelivery",
          "logs:CreateLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery"
        ]
        Resource = "*"
      },
      {
        # CloudWatch metric alarms for portal/range. PutMetricAlarm and
        # DeleteAlarms accept a resource ARN, but DescribeAlarms does not, so the
        # statement keeps Resource "*" and scopes by action instead.
        Sid    = "CloudWatchAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarms",
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource",
          # CloudWatch dashboards (portal capacity dashboard, modules/portal/ec2
          # observability.tf). Dashboard APIs do not support resource-level
          # scoping, so they share the statement's Resource "*".
          "cloudwatch:PutDashboard",
          "cloudwatch:GetDashboard",
          "cloudwatch:DeleteDashboards",
          "cloudwatch:ListDashboards"
        ]
        Resource = "*"
      },
      {
        Sid    = "SNS"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:ListTagsForResource",
          "sns:TagResource",
          "sns:UntagResource",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:GetSubscriptionAttributes",
          # RDS CreateEventSubscription runs a connectivity test-publish to the
          # target topic authorized with the *caller's* identity, so the deploy
          # role must hold sns:Publish on the managed topics or the backup-alerts
          # event subscription create fails with SNSNoAuthorization.
          "sns:Publish"
        ]
        Resource = [
          "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-portal-*",
          "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-range-*"
        ]
      },
      {
        Sid    = "SQS"
        Effect = "Allow"
        Action = ["sqs:*"]
        Resource = [
          "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-portal-*",
          "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-range-*"
        ]
      },
      {
        # SES domain identity + DKIM for portal transactional email. Identity
        # actions are not ARN-addressable, so the statement scopes by action and
        # keeps Resource "*".
        Sid    = "SES"
        Effect = "Allow"
        Action = [
          "ses:VerifyDomainIdentity",
          "ses:VerifyDomainDkim",
          "ses:DeleteIdentity",
          "ses:GetIdentityVerificationAttributes",
          "ses:GetIdentityDkimAttributes",
          "ses:SetIdentityDkimEnabled",
          "ses:GetIdentityMailFromDomainAttributes",
          "ses:GetIdentityNotificationAttributes",
          "ses:ListIdentities"
        ]
        Resource = "*"
      },
      {
        # Kinesis Firehose delivery streams for WAF / portal log pipelines.
        Sid    = "Firehose"
        Effect = "Allow"
        Action = ["firehose:*"]
        Resource = [
          "arn:aws:firehose:${var.aws_region}:${data.aws_caller_identity.current.account_id}:deliverystream/*-portal-*",
          "arn:aws:firehose:${var.aws_region}:${data.aws_caller_identity.current.account_id}:deliverystream/aws-waf-logs-*"
        ]
      },
      {
        Sid    = "EventBridge"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:EnableRule",
          "events:DisableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:ListTagsForResource",
          "events:TagResource",
          "events:UntagResource"
        ]
        Resource = "arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/*-portal-*"
      },
      {
        Sid    = "Budgets"
        Effect = "Allow"
        Action = [
          "budgets:ViewBudget",
          "budgets:ModifyBudget",
          "budgets:ListTagsForResource",
          "budgets:TagResource",
          "budgets:UntagResource"
        ]
        Resource = "arn:aws:budgets::${data.aws_caller_identity.current.account_id}:budget/shifter-*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Policy Attachments
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "compute" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.compute.arn
}

resource "aws_iam_role_policy_attachment" "networking" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.networking.arn
}

resource "aws_iam_role_policy_attachment" "data" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.data.arn
}

resource "aws_iam_role_policy_attachment" "security" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.security.arn
}

resource "aws_iam_role_policy_attachment" "management" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.management.arn
}

# ------------------------------------------------------------------------------
# Migration: safe detach-before-attach rollout for the #254 consolidation
#
# The role already holds AWS's hard maximum of 10 managed-policy attachments.
# Going to 5 attachments cannot be done by introducing 5 brand-new attachment
# resources while the 10 old ones are orphaned: Terraform does not guarantee it
# destroys orphaned attachments before creating new ones, so the role would
# momentarily exceed 10 attachments mid-apply and AWS would reject it with
# LimitExceededException.
#
# These `moved` blocks repoint five existing attachment addresses onto the five
# consolidated policies instead. Because each address already exists in state,
# Terraform treats the policy_arn change as an in-place REPLACEMENT (policy_arn
# is ForceNew), which under the default lifecycle is destroy-before-create:
# the old policy is detached, then the new one attached, on the same address -
# the count never rises. The remaining five old attachment resources
# (core_infrastructure, elb_acm, lambda_ops, secrets_kms, network_firewall) are
# absent from the config and are destroyed (detached), taking the role from 10
# down to 5. The role therefore stays at or below 10 attachments at every point
# of the apply, with no net-new attachment addresses created.
#
# On a fresh environment with no prior state these blocks are no-ops and the
# five attachments are created normally (nothing to exceed). The blocks are
# one-time migration aids; they may be removed once every environment's global
# IAM state has been applied.
# ------------------------------------------------------------------------------

moved {
  from = aws_iam_role_policy_attachment.ec2_instances
  to   = aws_iam_role_policy_attachment.compute
}

moved {
  from = aws_iam_role_policy_attachment.vpc_networking
  to   = aws_iam_role_policy_attachment.networking
}

moved {
  from = aws_iam_role_policy_attachment.rds
  to   = aws_iam_role_policy_attachment.data
}

moved {
  from = aws_iam_role_policy_attachment.iam_scoped
  to   = aws_iam_role_policy_attachment.security
}

moved {
  from = aws_iam_role_policy_attachment.ssm_cognito
  to   = aws_iam_role_policy_attachment.management
}

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "github_actions_role_arn" {
  description = "ARN of the IAM role for GitHub Actions (add to GitHub secrets as AWS_ROLE_ARN)"
  value       = aws_iam_role.github_actions.arn
}

output "github_actions_image_role_arn" {
  description = "ARN of the least-privilege base-image-pipeline role for packer.yml base builds (add to GitHub secrets as AWS_IMAGE_ROLE_ARN_<ENV>) (#1656)"
  value       = aws_iam_role.github_actions_image.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider"
  value       = aws_iam_openid_connect_provider.github.arn
}
