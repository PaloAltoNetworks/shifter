# Tenant-supplied code runs only on a dedicated gVisor pool. The runtime is a
# reviewed point release with an embedded checksum, never a latest-channel fetch.
locals {
  runtime_plugin_release = "20260914.0"
  runtime_plugin_sha512  = "ff1c0577c8daa0e3511aedad554c3d5e20fa184b4ddd422454f573d60a8b9774f972755ca5c7f56588c5b4f42345b60b2ead077f35d7d3235e23f57c0fa194ca"
  runtime_plugin_node_config = yamlencode({
    apiVersion = "node.eks.aws/v1alpha1"
    kind       = "NodeConfig"
    spec = {
      cluster = {
        name                 = aws_eks_cluster.this.name
        apiServerEndpoint    = aws_eks_cluster.this.endpoint
        certificateAuthority = aws_eks_cluster.this.certificate_authority[0].data
        cidr                 = aws_eks_cluster.this.kubernetes_network_config[0].service_ipv4_cidr
      }
      containerd = {
        # Nodeadm merges this into its stock config and migrates v2 to v3 on
        # containerd 2.x. It preserves the CNI and ordinary system DaemonSets.
        config = <<-TOML
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
            runtime_type = "io.containerd.runsc.v1"
          [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc.options]
            TypeUrl = "io.containerd.runsc.v1.options"
            ConfigPath = "/etc/containerd/runsc.toml"
        TOML
      }
    }
  })
}

resource "aws_launch_template" "runtime_plugins" {
  count                  = var.enable_runtime_plugins ? 1 : 0
  name_prefix            = "${var.cluster_name}-runtime-plugins-"
  update_default_version = true
  user_data = base64encode(templatefile("${path.module}/runtime-plugins-userdata.tftpl", {
    release     = local.runtime_plugin_release
    checksum    = local.runtime_plugin_sha512
    node_config = local.runtime_plugin_node_config
  }))

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
  monitoring { enabled = true }
  tag_specifications {
    resource_type = "instance"
    tags          = merge(var.tags, { Name = "${var.cluster_name}-runtime-plugins" })
  }
  tag_specifications {
    resource_type = "volume"
    tags          = merge(var.tags, { Name = "${var.cluster_name}-runtime-plugins" })
  }
  tags = var.tags
}

# The pool's own node role keeps its nodes' AWS identity apart from the platform
# pool. Pool membership is the node group's Auto Scaling group: the trusted
# node-pool labeler (shared.cloud.eks_node_pool_labeler) applies the
# node-restriction.kubernetes.io/shifter-pool=runtime-plugin label only to nodes
# whose aws:autoscaling:groupName tag names it. A kubelet cannot set that label
# (NodeRestriction), and only AWS can set aws:-prefixed tags.
resource "aws_iam_role" "runtime_plugin_node" {
  count                = var.enable_runtime_plugins ? 1 : 0
  name                 = "${var.cluster_name}-runtime-plugin-node"
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

resource "aws_iam_role_policy_attachment" "runtime_plugin_node" {
  for_each = var.enable_runtime_plugins ? toset([
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
  ]) : toset([])

  role       = aws_iam_role.runtime_plugin_node[0].name
  policy_arn = each.value
}

resource "aws_eks_node_group" "runtime_plugins" {
  count           = var.enable_runtime_plugins ? 1 : 0
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "runtime-plugins"
  node_role_arn   = aws_iam_role.runtime_plugin_node[0].arn
  subnet_ids      = [for subnet in aws_subnet.private : subnet.id]
  version         = var.kubernetes_version
  ami_type        = "AL2023_x86_64_STANDARD"
  instance_types  = ["m7i.large"]
  capacity_type   = "ON_DEMAND"
  # No labels: the pool label is applied by the trusted labeler, never the kubelet.
  taint {
    key    = "shifter.dev/runtime-plugin"
    value  = "true"
    effect = "NO_SCHEDULE"
  }
  launch_template {
    id      = aws_launch_template.runtime_plugins[0].id
    version = aws_launch_template.runtime_plugins[0].latest_version
  }
  # Keep a sandbox ready: cold EC2 bootstrap exceeds the installation probe's
  # deadline. Autoscaling never removes the final warm node.
  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 3
  }
  update_config { max_unavailable = 1 }
  lifecycle { ignore_changes = [scaling_config[0].desired_size] }
  # Like the platform node group, these nodes cannot reach Ready until the vpc-cni
  # and kube-proxy addons exist, so order them after both addons.
  depends_on = [
    aws_iam_role_policy_attachment.runtime_plugin_node,
    aws_eks_addon.vpc_cni,
    aws_eks_addon.kube_proxy,
  ]
  tags = merge(var.tags, { Name = "${var.cluster_name}-runtime-plugins" })
}

resource "aws_autoscaling_group_tag" "runtime_plugins_enabled" {
  count                  = var.enable_runtime_plugins ? 1 : 0
  autoscaling_group_name = aws_eks_node_group.runtime_plugins[0].resources[0].autoscaling_groups[0].name
  tag {
    key                 = "k8s.io/cluster-autoscaler/enabled"
    value               = "true"
    propagate_at_launch = false
  }
}

resource "aws_autoscaling_group_tag" "runtime_plugins_owned" {
  count                  = var.enable_runtime_plugins ? 1 : 0
  autoscaling_group_name = aws_eks_node_group.runtime_plugins[0].resources[0].autoscaling_groups[0].name
  tag {
    key                 = "k8s.io/cluster-autoscaler/${var.cluster_name}"
    value               = "owned"
    propagate_at_launch = false
  }
}
