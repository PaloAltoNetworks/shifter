mock_provider "aws" {}

override_resource {
  target = aws_iam_role.cluster
  values = {
    arn = "arn:aws:iam::123456789012:role/shifter-test-cluster"
  }
}

override_resource {
  target = aws_iam_role.node
  values = {
    arn = "arn:aws:iam::123456789012:role/shifter-test-node"
  }
}

override_resource {
  target = aws_iam_role.vpc_flow_logs
  values = {
    arn = "arn:aws:iam::123456789012:role/shifter-test-vpc-flow-logs"
  }
}

override_resource {
  target = aws_iam_role.workload["cni"]
  values = {
    arn = "arn:aws:iam::123456789012:role/shifter-test-cni"
  }
}

override_resource {
  target = aws_iam_role.workload["ebs-csi"]
  values = {
    arn = "arn:aws:iam::123456789012:role/shifter-test-ebs-csi"
  }
}

override_resource {
  target = aws_iam_role.workload["efs-csi"]
  values = {
    arn = "arn:aws:iam::123456789012:role/shifter-test-efs-csi"
  }
}

override_resource {
  target = aws_iam_policy.cluster_autoscaler
  values = {
    arn = "arn:aws:iam::123456789012:policy/shifter-test-cluster-autoscaler"
  }
}

override_resource {
  target = aws_eks_node_group.this
  values = {
    resources = [{
      autoscaling_groups = [{
        name = "eks-shifter-test-mock-asg"
      }]
    }]
  }
}

override_resource {
  target = aws_kms_key.cluster
  values = {
    arn = "arn:aws:kms:us-east-2:123456789012:key/11111111-1111-1111-1111-111111111111"
  }
}

override_resource {
  target = aws_kms_key.secrets
  values = {
    arn = "arn:aws:kms:us-east-2:123456789012:key/22222222-2222-2222-2222-222222222222"
  }
}

override_resource {
  target = aws_cloudwatch_log_group.vpc_flow
  values = {
    arn = "arn:aws:logs:us-east-2:123456789012:log-group:/aws/vpc/shifter-test/flow"
  }
}

override_resource {
  target = aws_cloudwatch_log_group.waf
  values = {
    arn = "arn:aws:logs:us-east-2:123456789012:log-group:aws-waf-logs-shifter-test-ingress"
  }
}

override_resource {
  target = aws_wafv2_web_acl.ingress
  values = {
    arn = "arn:aws:wafv2:us-east-2:123456789012:regional/webacl/shifter-test-ingress/11111111-1111-1111-1111-111111111111"
  }
}

override_resource {
  target = aws_subnet.private["us-east-2a"]
  values = {
    id = "subnet-mock-private-a"
  }
}

override_resource {
  target = aws_subnet.private["us-east-2b"]
  values = {
    id = "subnet-mock-private-b"
  }
}

override_resource {
  target = aws_eks_cluster.this
  values = {
    arn      = "arn:aws:eks:us-east-2:123456789012:cluster/shifter-test"
    endpoint = "https://example.test"
    certificate_authority = [{
      data = "dGVzdA=="
    }]
    identity = [{
      oidc = [{
        issuer = "https://oidc.eks.us-east-2.amazonaws.com/id/EXAMPLE"
      }]
    }]
  }
}

override_resource {
  target = aws_launch_template.node
  values = {
    id             = "lt-11111111111111111"
    latest_version = 1
  }
}

variables {
  environment              = "test"
  aws_region               = "us-east-2"
  cluster_name             = "shifter-test"
  deployment_role_arn      = "arn:aws:iam::123456789012:role/shifter-test-deploy"
  permissions_boundary_arn = "arn:aws:iam::123456789012:policy/shifter-test-ci-role-boundary"
  vpc_cidr                 = "10.42.0.0/16"
  availability_zones       = ["us-east-2a", "us-east-2b"]
  private_subnet_cidrs     = ["10.42.0.0/20", "10.42.16.0/20"]
  public_subnet_cidrs      = ["10.42.128.0/24", "10.42.129.0/24"]
  kubernetes_version       = "1.31"
  domain_name              = "shifter.test.example.com"
  oidc_thumbprints         = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
  node_instance_types      = ["m7i.large"]
  addon_versions = {
    vpc_cni           = "v1.22.4-eksbuild.3"
    ebs_csi           = "v1.63.1-eksbuild.1"
    efs_csi           = "v3.4.1-eksbuild.1"
    coredns           = "v1.11.4-eksbuild.40"
    kube_proxy        = "v1.31.14-eksbuild.25"
    secrets_store_csi = "v3.1.2-eksbuild.1"
  }
  workload_identities = {
    cni = {
      namespace       = "kube-system"
      service_account = "aws-node"
      policy_arns     = ["arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"]
    }
    ingress = {
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
    }
    portal = {
      namespace       = "shifter-platform"
      service_account = "shifter-portal"
      policy_arns     = ["arn:aws:iam::123456789012:policy/shifter-test-portal"]
    }
    provisionerLauncher = {
      namespace       = "shifter-platform"
      service_account = "provisioner-launcher"
      secret_names    = ["database", "django"]
    }
    provisioner = {
      namespace       = "shifter-jobs"
      service_account = "provisioner"
      secret_names    = ["database", "django"]
    }
    ebs-csi = {
      namespace       = "kube-system"
      service_account = "ebs-csi-controller-sa"
      policy_arns     = ["arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"]
    }
    efs-csi = {
      namespace       = "kube-system"
      service_account = "efs-csi-controller-sa"
      policy_arns     = ["arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy"]
    }
  }
  secret_names = [
    "database",
    "django",
  ]
  tags = {
    Environment = "test"
    Project     = "shifter"
  }
}

run "security_contract" {
  command = apply

  assert {
    condition     = aws_eks_cluster.this.vpc_config[0].endpoint_private_access && !aws_eks_cluster.this.vpc_config[0].endpoint_public_access
    error_message = "The EKS API endpoint must be private and must not expose public access."
  }

  assert {
    condition     = !contains([for attachment in aws_iam_role_policy_attachment.node : attachment.policy_arn], "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy")
    error_message = "The CNI policy must use exact service-account identity, not node-wide credentials."
  }

  assert {
    condition = alltrue(concat(
      [
        aws_iam_role.cluster.permissions_boundary == var.permissions_boundary_arn,
        aws_iam_role.node.permissions_boundary == var.permissions_boundary_arn,
        aws_iam_role.cluster_autoscaler.permissions_boundary == var.permissions_boundary_arn,
        aws_iam_role.vpc_flow_logs.permissions_boundary == var.permissions_boundary_arn,
      ],
      [for role in aws_iam_role.workload : role.permissions_boundary == var.permissions_boundary_arn],
    ))
    error_message = "Every EKS-created IAM role must carry the installation CI permissions boundary."
  }

  assert {
    condition     = aws_launch_template.node.block_device_mappings[0].ebs[0].encrypted && aws_launch_template.node.metadata_options[0].http_tokens == "required"
    error_message = "Managed nodes must use encrypted disks and require IMDSv2."
  }

  assert {
    condition     = length(aws_eks_cluster.this.encryption_config) == 1 && aws_eks_cluster.this.encryption_config[0].resources == toset(["secrets"])
    error_message = "The EKS cluster must encrypt Kubernetes secrets with a customer-managed KMS key."
  }

  assert {
    condition     = aws_eks_cluster.this.access_config[0].authentication_mode == "API" && !aws_eks_cluster.this.access_config[0].bootstrap_cluster_creator_admin_permissions
    error_message = "Cluster access must use explicit access entries without an implicit creator-admin grant."
  }

  assert {
    condition     = aws_kms_key.cluster.enable_key_rotation && aws_kms_key.secrets.enable_key_rotation
    error_message = "Cluster and secret-store KMS keys must rotate automatically."
  }

  assert {
    condition     = toset(aws_eks_node_group.this.subnet_ids) == toset([for subnet in aws_subnet.private : subnet.id])
    error_message = "The managed node group must use only private subnets."
  }

  assert {
    condition     = aws_iam_openid_connect_provider.cluster.client_id_list == toset(["sts.amazonaws.com"])
    error_message = "IRSA trust must use the STS audience."
  }

  assert {
    condition     = strcontains(aws_iam_role.workload["portal"].assume_role_policy, "system:serviceaccount:shifter-platform:shifter-portal")
    error_message = "Workload identity must bind an exact namespace and service-account subject."
  }

  assert {
    condition     = !strcontains(aws_iam_role.workload["portal"].assume_role_policy, "system:serviceaccount:*")
    error_message = "Workload identity must not trust wildcard service-account subjects."
  }

  # #1826: every workload IRSA role, including the launcher/provisioner and the
  # add-on controllers, must bind exactly one exact namespace/service-account
  # subject so no service account can assume another's role.
  assert {
    condition = alltrue([
      for name, identity in var.workload_identities :
      strcontains(
        aws_iam_role.workload[name].assume_role_policy,
        "system:serviceaccount:${identity.namespace}:${identity.service_account}"
      )
    ])
    error_message = "Every workload identity must bind its exact namespace/service-account subject."
  }

  assert {
    condition = alltrue([
      for name in keys(var.workload_identities) :
      !strcontains(aws_iam_role.workload[name].assume_role_policy, "system:serviceaccount:*")
    ])
    error_message = "No workload identity may trust a wildcard service-account subject."
  }

  # The privileged provisioner Job runs as the dedicated shifter-jobs/provisioner
  # subject, and the dedicated launcher creates those Jobs; neither may reuse the
  # other's identity.
  assert {
    condition     = strcontains(aws_iam_role.workload["provisioner"].assume_role_policy, "system:serviceaccount:shifter-jobs:provisioner")
    error_message = "The provisioner IRSA role must bind the exact shifter-jobs/provisioner subject."
  }

  assert {
    condition     = strcontains(aws_iam_role.workload["provisionerLauncher"].assume_role_policy, "system:serviceaccount:shifter-platform:provisioner-launcher")
    error_message = "The provisioner-launcher IRSA role must bind the exact shifter-platform/provisioner-launcher subject."
  }

  # cluster-autoscaler is a dedicated exact-subject role; its write permissions
  # are scoped to ASGs this cluster owns, never every ASG in the account.
  assert {
    condition     = strcontains(aws_iam_role.cluster_autoscaler.assume_role_policy, "system:serviceaccount:kube-system:cluster-autoscaler")
    error_message = "The cluster-autoscaler IRSA role must bind the exact kube-system/cluster-autoscaler subject."
  }

  assert {
    condition     = strcontains(aws_iam_policy.cluster_autoscaler.policy, "k8s.io/cluster-autoscaler/${var.cluster_name}")
    error_message = "cluster-autoscaler capacity writes must be scoped to ASGs this cluster owns."
  }

  # The VPC CNI network-policy agent must be enabled so the chart's default-deny
  # NetworkPolicies are actually enforced on EKS, not merely rendered.
  assert {
    condition     = strcontains(aws_eks_addon.vpc_cni.configuration_values, "enableNetworkPolicy") && strcontains(aws_eks_addon.vpc_cni.configuration_values, "NETWORK_POLICY_ENFORCING_MODE") && strcontains(aws_eks_addon.vpc_cni.configuration_values, "strict")
    error_message = "The vpc-cni add-on must enable the NetworkPolicy agent in strict startup mode."
  }

  assert {
    condition = (
      aws_eks_addon.vpc_cni.addon_version == var.addon_versions.vpc_cni &&
      aws_eks_addon.ebs_csi.addon_version == var.addon_versions.ebs_csi &&
      aws_eks_addon.efs_csi.addon_version == var.addon_versions.efs_csi &&
      aws_eks_addon.core_dns.addon_version == var.addon_versions.coredns &&
      aws_eks_addon.kube_proxy.addon_version == var.addon_versions.kube_proxy &&
      aws_eks_addon.secrets_store_csi.addon_version == var.addon_versions.secrets_store_csi
    )
    error_message = "Every managed EKS add-on must use an explicit reviewed version."
  }

  assert {
    condition     = aws_eks_addon.secrets_store_csi.service_account_role_arn == null
    error_message = "The Secrets Store CSI provider must not receive a controller-wide secret-reader role."
  }

  assert {
    condition     = aws_iam_role_policy.load_balancer_controller.role == aws_iam_role.workload["ingress"].id
    error_message = "The module-owned Load Balancer Controller policy must attach only to the exact ingress IRSA role."
  }

  # EBS/EFS CSI drivers are installed as managed add-ons bound to their own
  # exact-subject IRSA roles (least-privilege controller identity).
  assert {
    condition     = aws_eks_addon.ebs_csi.service_account_role_arn == aws_iam_role.workload["ebs-csi"].arn && aws_eks_addon.efs_csi.service_account_role_arn == aws_iam_role.workload["efs-csi"].arn
    error_message = "The EBS and EFS CSI add-ons must use their dedicated controller IRSA roles."
  }

  # The autoscaler-discovery tags are applied to the managed node group's ASG so
  # cluster-autoscaler can find the ASG it owns.
  assert {
    condition     = aws_autoscaling_group_tag.cluster_autoscaler_owned.tag[0].key == "k8s.io/cluster-autoscaler/${var.cluster_name}"
    error_message = "The node group ASG must carry the cluster-autoscaler owned-discovery tag."
  }

  assert {
    condition     = alltrue([for secret in aws_secretsmanager_secret.platform : secret.kms_key_id == aws_kms_key.secrets.arn])
    error_message = "Platform secret stores must use the dedicated customer-managed KMS key."
  }

  assert {
    condition     = aws_acm_certificate.ingress.validation_method == "DNS" && aws_wafv2_web_acl.ingress.scope == "REGIONAL"
    error_message = "AWS ingress prerequisites must include a DNS-validated regional certificate and regional WAF."
  }

  assert {
    condition     = aws_cloudwatch_log_group.cluster.retention_in_days >= 365 && aws_cloudwatch_log_group.vpc_flow.retention_in_days >= 365 && aws_cloudwatch_log_group.waf.retention_in_days >= 365
    error_message = "EKS, VPC flow, and WAF logs must be retained for at least one year."
  }

  assert {
    condition     = aws_flow_log.this.traffic_type == "ALL" && aws_flow_log.this.log_destination == aws_cloudwatch_log_group.vpc_flow.arn
    error_message = "The EKS VPC must publish all flow records to the encrypted log group."
  }

  assert {
    condition     = length(aws_default_security_group.this.ingress) == 0 && length(aws_default_security_group.this.egress) == 0
    error_message = "The EKS VPC default security group must deny all traffic."
  }

  assert {
    condition     = contains([for rule in aws_wafv2_web_acl.ingress.rule : rule.name], "AWSManagedRulesKnownBadInputsRuleSet")
    error_message = "The ingress WAF must enable AWS managed known-bad-input protection."
  }

  assert {
    condition     = aws_wafv2_web_acl_logging_configuration.ingress.resource_arn == aws_wafv2_web_acl.ingress.arn
    error_message = "The ingress WAF must publish request logs."
  }
}
