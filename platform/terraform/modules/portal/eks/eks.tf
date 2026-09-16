resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.cluster_name}/cluster"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.cluster.arn

  tags = var.tags
}

resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  enabled_cluster_log_types = [
    "api",
    "audit",
    "authenticator",
    "controllerManager",
    "scheduler",
  ]

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }

  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = aws_kms_key.cluster.arn
    }
  }

  vpc_config {
    endpoint_private_access = true
    endpoint_public_access  = false
    subnet_ids              = [for subnet in aws_subnet.private : subnet.id]
  }

  depends_on = [
    aws_cloudwatch_log_group.cluster,
    aws_iam_role_policy.cluster_kms,
    aws_iam_role_policy_attachment.cluster,
  ]

  tags = var.tags
}

resource "aws_eks_access_entry" "deployment" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = var.deployment_role_arn
  type          = "STANDARD"

  tags = var.tags
}

resource "aws_eks_access_policy_association" "deployment" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_eks_access_entry.deployment.principal_arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

resource "aws_eks_node_group" "this" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "platform"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = [for subnet in aws_subnet.private : subnet.id]
  version         = var.kubernetes_version
  instance_types  = var.node_instance_types
  capacity_type   = "ON_DEMAND"

  launch_template {
    id      = aws_launch_template.node.id
    version = aws_launch_template.node.latest_version
  }

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable_percentage = 25
  }

  # cluster-autoscaler owns desired capacity within [min_size, max_size] (#1826).
  # Without this, every Terraform apply would reset desired_size back to the
  # static var and fight the autoscaler over the live node count.
  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }

  depends_on = [aws_iam_role_policy_attachment.node]

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-platform"
  })
}

# cluster-autoscaler auto-discovers the managed node group's ASG by these tags
# (#1826). EKS creates the ASG, so tag it explicitly rather than relying on
# node-group tag propagation.
resource "aws_autoscaling_group_tag" "cluster_autoscaler_enabled" {
  autoscaling_group_name = aws_eks_node_group.this.resources[0].autoscaling_groups[0].name

  tag {
    key                 = "k8s.io/cluster-autoscaler/enabled"
    value               = "true"
    propagate_at_launch = false
  }
}

resource "aws_autoscaling_group_tag" "cluster_autoscaler_owned" {
  autoscaling_group_name = aws_eks_node_group.this.resources[0].autoscaling_groups[0].name

  tag {
    key                 = "k8s.io/cluster-autoscaler/${var.cluster_name}"
    value               = "owned"
    propagate_at_launch = false
  }
}

resource "aws_launch_template" "node" {
  name_prefix            = "${var.cluster_name}-node-"
  update_default_version = true

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      delete_on_termination = true
      encrypted             = true
      volume_size           = var.node_disk_size
      volume_type           = "gp3"
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
    http_tokens                 = "required"
    instance_metadata_tags      = "disabled"
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags = merge(var.tags, {
      Name = "${var.cluster_name}-node"
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags = merge(var.tags, {
      Name = "${var.cluster_name}-node"
    })
  }

  tags = var.tags
}

resource "aws_eks_addon" "vpc_cni" {
  cluster_name             = aws_eks_cluster.this.name
  addon_name               = "vpc-cni"
  addon_version            = var.addon_versions.vpc_cni
  service_account_role_arn = aws_iam_role.workload["cni"].arn

  # Enforce Kubernetes NetworkPolicies on EKS (#1826). The chart renders the
  # default-deny + scoped-allow policies for both clouds, but on EKS they are
  # inert unless the VPC CNI network-policy agent is enabled — this closes the
  # "rendered but not enforced" gap so NetworkPolicy parity with GKE is real.
  configuration_values = jsonencode({
    enableNetworkPolicy = "true"
    env = {
      NETWORK_POLICY_ENFORCING_MODE = "strict"
    }
  })

  depends_on = [aws_eks_node_group.this]

  tags = var.tags
}

resource "aws_eks_addon" "ebs_csi" {
  cluster_name             = aws_eks_cluster.this.name
  addon_name               = "aws-ebs-csi-driver"
  addon_version            = var.addon_versions.ebs_csi
  service_account_role_arn = aws_iam_role.workload["ebs-csi"].arn

  depends_on = [aws_eks_node_group.this]

  tags = var.tags
}

resource "aws_eks_addon" "efs_csi" {
  cluster_name             = aws_eks_cluster.this.name
  addon_name               = "aws-efs-csi-driver"
  addon_version            = var.addon_versions.efs_csi
  service_account_role_arn = aws_iam_role.workload["efs-csi"].arn

  depends_on = [aws_eks_node_group.this]

  tags = var.tags
}

resource "aws_eks_addon" "core_dns" {
  cluster_name  = aws_eks_cluster.this.name
  addon_name    = "coredns"
  addon_version = var.addon_versions.coredns

  depends_on = [aws_eks_node_group.this]

  tags = var.tags
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name  = aws_eks_cluster.this.name
  addon_name    = "kube-proxy"
  addon_version = var.addon_versions.kube_proxy

  depends_on = [aws_eks_node_group.this]

  tags = var.tags
}

resource "aws_eks_addon" "secrets_store_csi" {
  cluster_name  = aws_eks_cluster.this.name
  addon_name    = "aws-secrets-store-csi-driver-provider"
  addon_version = var.addon_versions.secrets_store_csi

  # The provider itself receives no IAM role. Each future SecretProviderClass
  # consumer continues to use its own exact-subject workload IRSA role.
  depends_on = [aws_eks_node_group.this]

  tags = var.tags
}
