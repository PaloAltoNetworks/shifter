locals {
  workload_policy_attachments = merge([
    for identity_name, identity in var.workload_identities : {
      for policy_arn in identity.policy_arns :
      "${identity_name}:${policy_arn}" => {
        identity_name = identity_name
        policy_arn    = policy_arn
      }
    }
  ]...)
  workload_secret_access = {
    for identity_name, identity in var.workload_identities :
    identity_name => identity
    if length(identity.secret_names) > 0
  }
  workload_object_read_access = {
    for identity_name, identity in var.workload_identities :
    identity_name => identity.object_read_arns
    if length(identity.object_read_arns) > 0
  }
  workload_rds_iam_access = {
    for identity_name, identity in var.workload_identities :
    identity_name => identity.rds_iam_db_user
    if identity.rds_iam_db_user != ""
  }
  workload_feature_artifact_store_write = toset([
    for identity_name, identity in var.workload_identities :
    identity_name
    if identity.feature_artifact_store_write
  ])
  workload_feature_artifact_store_read = toset([
    for identity_name, identity in var.workload_identities :
    identity_name
    if identity.feature_artifact_store_read
  ])
  workload_node_pool_labeler = toset([
    for identity_name, identity in var.workload_identities :
    identity_name
    if identity.node_pool_labeler
  ])
  workload_platform_application_access = toset([
    for identity_name, identity in var.workload_identities :
    identity_name
    if identity.platform_application_access
  ])
  # Platform task queues, by the portal stack's stable names (ADR-044-R6).
  platform_queue_keys        = toset(["cms", "engine", "mc"])
  platform_metric_namespaces = ["Shifter/PortalCapacity", "Shifter/WarmPool", "Shifter/CtfCommunication"]
  workload_range_participant_secret_access = toset([
    for identity_name, identity in var.workload_identities :
    identity_name
    if identity.range_participant_secret_read
  ])
  # Participant-delivery kinds the provisioner stores under
  # shifter/<env>/range/<range_id>/raes/<kind>/<digest> (ec2_guest_secrets._KINDS).
  # host-ssh / host-identity (provisioner management) and domain-dsrm /
  # domain-authority (directory admin) are deliberately absent.
  range_participant_secret_arns = [
    for kind in ["account-key", "account-password", "domain-account"] :
    "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter/${var.environment}/range/*/raes/${kind}/*"
  ]
}

# The shared portal RDS instance is created by the portal core stack and read by
# stable name (ADR-044-R6: "${environment}-portal-*"); its DbiResourceId anchors
# the rds-db:connect ARN below.
data "aws_db_instance" "portal" {
  db_instance_identifier = "${var.environment}-portal-db"
}

resource "aws_iam_role" "cluster" {
  name                 = "${var.cluster_name}-cluster"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy" "cluster_kms" {
  name = "cluster-kms"
  role = aws_iam_role.cluster.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "kms:CreateGrant",
        "kms:DescribeKey",
      ]
      Resource = aws_kms_key.cluster.arn
      Condition = {
        Bool = {
          "kms:GrantIsForAWSResource" = "true"
        }
      }
    }]
  })
}

resource "aws_iam_role" "node" {
  name                 = "${var.cluster_name}-node"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
  ])

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

resource "aws_iam_openid_connect_provider" "cluster" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = var.oidc_thumbprints

  tags = var.tags
}

resource "aws_iam_role" "workload" {
  for_each = var.workload_identities

  name                 = "${var.cluster_name}-${each.key}"
  permissions_boundary = var.permissions_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.cluster.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")}:aud" = "sts.amazonaws.com"
          "${replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")}:sub" = "system:serviceaccount:${each.value.namespace}:${each.value.service_account}"
        }
      }
    }]
  })

  tags = merge(var.tags, {
    KubernetesNamespace      = each.value.namespace
    KubernetesServiceAccount = each.value.service_account
  })
}

resource "aws_iam_role_policy_attachment" "workload" {
  for_each = local.workload_policy_attachments

  role       = aws_iam_role.workload[each.value.identity_name].name
  policy_arn = each.value.policy_arn
}

resource "aws_iam_role_policy" "workload_secrets" {
  for_each = local.workload_secret_access

  name = "exact-secret-access"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetSecretValue",
        ]
        Resource = [
          for secret_name in each.value.secret_names :
          aws_secretsmanager_secret.platform[secret_name].arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.secrets.arn
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy" "workload_object_read" {
  for_each = local.workload_object_read_access

  name = "exact-object-read"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = sort(tolist(each.value))
    }]
  })
}

# rds-db:connect for the workload's long-running RDS IAM-auth identity. Scoped to
# the exact dbuser (never wildcarded) so a workload can mint an auth token only
# for the Postgres role its entrypoint switches to, and for no other user.
resource "aws_iam_role_policy" "workload_rds_iam" {
  for_each = local.workload_rds_iam_access

  name = "rds-iam-auth"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${data.aws_db_instance.portal.resource_id}/${each.value}"
    }]
  })
}

# The provisioner encrypts range guest credentials with the portal Secrets Manager
# CMK (eks-provisioner-env SECRETS_KMS_KEY_ARN). Resolve it by the same alias so the
# reader's Decrypt grant and the writer's key can never diverge.
data "aws_kms_alias" "range_credential_secrets" {
  count = length(local.workload_range_participant_secret_access) > 0 ? 1 : 0
  name  = "alias/shifter-${var.environment}-secrets-manager"
}

# Read-only participant-delivery credentials for brokering a participant's SSH/RDP
# connection to a realized range guest (#1826; GCP parity with the portal's
# participant-prefix-conditioned secretAccessor). Decrypt is confined to Secrets
# Manager calls on exactly the participant-delivery secret ARNs via the SecretARN
# encryption context.
resource "aws_iam_role_policy" "workload_range_participant_secrets" {
  for_each = local.workload_range_participant_secret_access

  name = "range-participant-secret-read"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:DescribeSecret", "secretsmanager:GetSecretValue"]
        Resource = local.range_participant_secret_arns
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = data.aws_kms_alias.range_credential_secrets[0].target_key_arn
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
          StringLike = {
            "kms:EncryptionContext:SecretARN" = local.range_participant_secret_arns
          }
        }
      },
    ]
  })
}

# ------------------------------------------------------------------------------
# cluster-autoscaler IRSA (#1826)
# ------------------------------------------------------------------------------
# cluster-autoscaler needs a custom cluster-tag-scoped policy (no AWS-managed
# policy exists), so it is a dedicated exact-subject IRSA role rather than a
# workload_identities map entry: a computed policy ARN inside the map value would
# make the workload_policy_attachments for_each key unknown at plan time. The
# discovery reads require Resource=* per the AWS service authorization reference;
# the capacity writes are scoped to ASGs this cluster owns.

resource "aws_iam_policy" "cluster_autoscaler" {
  name        = "${var.cluster_name}-cluster-autoscaler"
  description = "cluster-autoscaler discovery + owned-ASG capacity management for ${var.cluster_name}."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AutoscalerDiscovery"
        Effect = "Allow"
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:DescribeImages",
          "ec2:GetInstanceTypesFromInstanceRequirements",
          "eks:DescribeNodegroup"
        ]
        Resource = "*"
      },
      {
        Sid    = "AutoscalerManageOwnedAsgs"
        Effect = "Allow"
        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${var.cluster_name}" = "owned"
          }
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role" "cluster_autoscaler" {
  name                 = "${var.cluster_name}-cluster-autoscaler"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.cluster.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")}:aud" = "sts.amazonaws.com"
          "${replace(aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://", "")}:sub" = "system:serviceaccount:kube-system:cluster-autoscaler"
        }
      }
    }]
  })

  tags = merge(var.tags, {
    KubernetesNamespace      = "kube-system"
    KubernetesServiceAccount = "cluster-autoscaler"
  })
}

resource "aws_iam_role_policy_attachment" "cluster_autoscaler" {
  role       = aws_iam_role.cluster_autoscaler.name
  policy_arn = aws_iam_policy.cluster_autoscaler.arn
}

# ------------------------------------------------------------------------------
# Platform application AWS access (#2466)
# ------------------------------------------------------------------------------
# The retired portal EC2 role carried the platform's SQS, SNS, storage and metrics
# permissions for the same Django processes these identities now run. Resources
# are the portal stack's, resolved by stable name (ADR-044-R6); every KMS key
# policy delegates to account IAM, and the storage bucket policy still enforces
# TLS and its own SSE-KMS key on every write.
data "aws_kms_alias" "portal_messaging" {
  count = length(local.workload_platform_application_access) > 0 ? 1 : 0
  name  = "alias/${var.environment}-portal-portal-messaging"
}

data "aws_kms_alias" "portal_storage" {
  count = length(local.workload_platform_application_access) + length(local.workload_feature_artifact_store_write) > 0 ? 1 : 0
  name  = "alias/shifter-${var.environment}-portal-s3"
}

resource "aws_iam_role_policy" "workload_platform_application" {
  for_each = local.workload_platform_application_access

  name = "platform-application-access"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PlatformTaskQueues"
        Effect = "Allow"
        Action = [
          "sqs:ChangeMessageVisibility",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:ReceiveMessage",
          "sqs:SendMessage",
        ]
        Resource = sort([for queue in local.platform_queue_keys : "arn:aws:sqs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.environment}-portal-${queue}-tasks"])
      },
      {
        Sid      = "RangeEventsPublish"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${var.environment}-portal-range-events"
      },
      {
        Sid      = "MessagingKms"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = data.aws_kms_alias.portal_messaging[0].target_key_arn
        Condition = {
          StringEquals = {
            "kms:ViaService" = ["sqs.${var.aws_region}.amazonaws.com", "sns.${var.aws_region}.amazonaws.com"]
          }
        }
      },
      {
        Sid    = "StorageObjects"
        Effect = "Allow"
        Action = [
          "s3:DeleteObject",
          "s3:GetObject",
          "s3:GetObjectTagging",
          "s3:PutObject",
          "s3:PutObjectTagging",
        ]
        Resource = "arn:aws:s3:::${var.storage_bucket_name}/*"
      },
      {
        Sid      = "StorageBucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.storage_bucket_name}"
      },
      {
        Sid      = "StorageKms"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey"]
        Resource = data.aws_kms_alias.portal_storage[0].target_key_arn
        Condition = {
          StringEquals = { "kms:ViaService" = "s3.${var.aws_region}.amazonaws.com" }
        }
      },
      {
        # PutMetricData has no resource-level scoping; the namespace condition is
        # the boundary.
        Sid      = "ApplicationMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = { "cloudwatch:namespace" = local.platform_metric_namespaces }
        }
      },
    ]
  })
}

# Isolated feature-artifact acquisition Job (ADR-034-R12, #2463): it may only
# write objects under the content-addressed delivery prefix (multipart SSE-KMS
# uploads need the storage key's Decrypt and GenerateDataKey). It cannot read,
# list, delete, or touch any other bucket path.
resource "aws_iam_role_policy" "workload_feature_artifact_store" {
  for_each = local.workload_feature_artifact_store_write

  name = "feature-artifact-store-write"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "FeatureArtifactObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::${var.storage_bucket_name}/${trim(var.feature_artifact_prefix, "/")}/*"
      },
      {
        Sid      = "FeatureArtifactStorageKms"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = data.aws_kms_alias.portal_storage[0].target_key_arn
        Condition = {
          StringEquals = { "kms:ViaService" = "s3.${var.aws_region}.amazonaws.com" }
        }
      },
    ]
  })
}

# Trusted runtime-plugin node-pool labeler (#2526): reads each EKS node's
# instance (state, DNS name and its AWS-set aws:autoscaling:groupName tag).
# ec2:DescribeInstances has no resource-level scoping.
resource "aws_iam_role_policy" "workload_node_pool_labeler" {
  for_each = local.workload_node_pool_labeler

  name = "node-pool-labeler"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DescribeNodeInstances"
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances"]
        Resource = "*"
      },
    ]
  })
}

# Deploy content bootstrap (acquire_feature_artifacts, ADR-034-R12): verifies an
# inventoried artifact still exists before reusing it. HEAD needs s3:GetObject,
# and only ListBucket turns a missing key into 404 instead of 403. With no
# storage-key KMS grant the identity cannot decrypt object bytes.
resource "aws_iam_role_policy" "workload_feature_artifact_store_read" {
  for_each = local.workload_feature_artifact_store_read

  name = "feature-artifact-store-read"
  role = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "FeatureArtifactObjectMetadata"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.storage_bucket_name}/${trim(var.feature_artifact_prefix, "/")}/*"
      },
      {
        Sid      = "FeatureArtifactMissingObjects"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = "arn:aws:s3:::${var.storage_bucket_name}"
      },
    ]
  })
}
