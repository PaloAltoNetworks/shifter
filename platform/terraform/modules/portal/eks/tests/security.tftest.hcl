override_data {
  target = data.aws_ssm_parameters_by_path.range_network
  values = {
    names  = ["/shifter/test/range/vpc_id", "/shifter/test/range/vpc_cidr", "/shifter/test/range/private_route_table_id"]
    values = ["vpc-mock-range", "10.50.0.0/16", "rtb-mock-range"]
  }
}

# Portal-stack keys for platform application access (#2466); queue and topic
# ARNs are built from their stable names, so they need no lookup.
override_data {
  target = data.aws_kms_alias.portal_messaging
  values = {
    target_key_arn = "arn:aws:kms:us-east-2:123456789012:key/mock-portal-messaging"
  }
}

override_data {
  target = data.aws_kms_alias.portal_storage
  values = {
    target_key_arn = "arn:aws:kms:us-east-2:123456789012:key/mock-portal-storage"
  }
}

# Portal Secrets Manager CMK the provisioner encrypts range guest credentials with.
override_data {
  target = data.aws_kms_alias.range_credential_secrets
  values = {
    target_key_arn = "arn:aws:kms:us-east-2:123456789012:key/mock-portal-secrets-manager"
  }
}

# Portal data plane discovered by name for the portal<->EKS peering
# (portal_network.tf). Under mock_provider these resolve to unknowns, which would
# break the peering precondition's cidrhost() math and the aws_route for_each, so
# pin concrete disjoint values (portal 10.0.0.0/16 vs eks 10.42.0.0/16, range 10.50.0.0/16).
override_data {
  target = data.aws_vpc.portal
  values = {
    id         = "vpc-mock-portal"
    cidr_block = "10.0.0.0/16"
  }
}

override_data {
  target = data.aws_route_tables.portal_private
  values = {
    ids = ["rtb-mock-portal-a", "rtb-mock-portal-b"]
  }
}

# GitHub Actions runner VPC discovered by name for the runner<->EKS peering
# (runner_network.tf). Disjoint from portal/eks/range CIDRs.
override_data {
  target = data.aws_vpc.runner
  values = {
    id         = "vpc-mock-runner"
    cidr_block = "10.20.0.0/24"
  }
}

override_data {
  target = data.aws_route_tables.runner
  values = {
    ids = ["rtb-mock-runner"]
  }
}

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
    arn                       = "arn:aws:eks:us-east-2:123456789012:cluster/shifter-test"
    endpoint                  = "https://example.test"
    kubernetes_network_config = { service_ipv4_cidr = "172.20.0.0/16" }
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

override_resource {
  target = aws_eks_node_group.runtime_plugins[0]
  values = {
    resources = [{ autoscaling_groups = [{ name = "eks-shifter-test-plugins-asg" }] }]
  }
}

override_resource {
  target = aws_launch_template.runtime_plugins[0]
  values = {
    id             = "lt-22222222222222222"
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
      namespace                     = "shifter-platform"
      service_account               = "shifter-portal"
      policy_arns                   = ["arn:aws:iam::123456789012:policy/shifter-test-portal"]
      range_participant_secret_read = true
      platform_application_access   = true
    }
    workers = {
      namespace                   = "shifter-platform"
      service_account             = "shifter-workers"
      platform_application_access = true
    }
    artifactAcquirer = {
      namespace                    = "shifter-acquisition"
      service_account              = "artifact-acquirer"
      feature_artifact_store_write = true
    }
    nodePoolLabeler = {
      namespace         = "shifter-platform"
      service_account   = "node-pool-labeler"
      node_pool_labeler = true
    }
    migrator = {
      namespace                   = "shifter-platform"
      service_account             = "migrator"
      feature_artifact_store_read = true
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
  storage_bucket_name = "test-storage-bucket"
  secret_names = [
    "database",
    "django",
    "guacamole-db",
    "guacamole-json-auth",
  ]
  # Validate the runtime-plugin sandbox pool contract; the trusted node-pool
  # labeler applies its restricted pool label (#2526).
  enable_runtime_plugins = true
  tags = {
    Environment = "test"
    Project     = "shifter"
  }
}

run "security_contract" {
  command = apply

  assert {
    condition = (
      aws_eks_node_group.runtime_plugins[0].ami_type == "AL2023_x86_64_STANDARD" &&
      length(coalesce(aws_eks_node_group.runtime_plugins[0].labels, {})) == 0 &&
      aws_eks_node_group.runtime_plugins[0].node_role_arn == aws_iam_role.runtime_plugin_node[0].arn &&
      aws_iam_role.runtime_plugin_node[0].arn != aws_iam_role.node.arn &&
      one(aws_eks_node_group.runtime_plugins[0].taint).key == "shifter.dev/runtime-plugin" &&
      one(aws_eks_node_group.runtime_plugins[0].taint).effect == "NO_SCHEDULE" &&
      aws_eks_node_group.runtime_plugins[0].scaling_config[0].min_size == 1
    )
    error_message = "Tenant runtime plugins require a warm, exclusive AL2023 sandbox pool with its own node role and no kubelet-set labels."
  }

  assert {
    condition = (
      keys(aws_iam_role_policy.workload_node_pool_labeler) == ["nodePoolLabeler"] &&
      jsondecode(aws_iam_role_policy.workload_node_pool_labeler["nodePoolLabeler"].policy).Statement[0].Action == ["ec2:DescribeInstances"] &&
      length(jsondecode(aws_iam_role_policy.workload_node_pool_labeler["nodePoolLabeler"].policy).Statement) == 1 &&
      !contains(keys(aws_iam_role_policy.workload_platform_application), "nodePoolLabeler") &&
      !contains(keys(aws_iam_role_policy.workload_rds_iam), "nodePoolLabeler") &&
      output.runtime_plugin_node_group_asg == "eks-shifter-test-plugins-asg"
    )
    error_message = "The node-pool labeler may only read node instances."
  }

  assert {
    condition = (
      aws_launch_template.runtime_plugins[0].metadata_options[0].http_tokens == "required" &&
      aws_launch_template.runtime_plugins[0].metadata_options[0].http_put_response_hop_limit == 1 &&
      aws_launch_template.runtime_plugins[0].block_device_mappings[0].ebs[0].encrypted
    )
    error_message = "Sandbox node storage and metadata must preserve the hardened node boundary."
  }

  assert {
    condition = (
      strcontains(base64decode(aws_launch_template.runtime_plugins[0].user_data), "sha512sum --check --status") &&
      strcontains(base64decode(aws_launch_template.runtime_plugins[0].user_data), "release/20260914.0/") &&
      strcontains(base64decode(aws_launch_template.runtime_plugins[0].user_data), "io.containerd.runsc.v1") &&
      strcontains(base64decode(aws_launch_template.runtime_plugins[0].user_data), "node.eks.aws/v1alpha1")
    )
    error_message = "Node bootstrap must verify the pinned gVisor archive and configure the runtime through nodeadm."
  }


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

  # Only identities that opt in may read range participant-delivery credentials.
  assert {
    condition     = keys(aws_iam_role_policy.workload_range_participant_secrets) == ["portal"]
    error_message = "Range participant-secret read must be granted only to identities that opt in (the portal)."
  }

  # GCP parity: participant-delivery kinds only. Provisioner management keys, host
  # identities and directory admin material must never be readable by the portal.
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.workload_range_participant_secrets["portal"].policy).Statement[0].Resource == [
        "arn:aws:secretsmanager:us-east-2:${data.aws_caller_identity.current.account_id}:secret:shifter/test/range/*/raes/account-key/*",
        "arn:aws:secretsmanager:us-east-2:${data.aws_caller_identity.current.account_id}:secret:shifter/test/range/*/raes/account-password/*",
        "arn:aws:secretsmanager:us-east-2:${data.aws_caller_identity.current.account_id}:secret:shifter/test/range/*/raes/domain-account/*",
      ] &&
      alltrue([
        for kind in ["host-ssh", "host-identity", "domain-dsrm", "domain-authority"] :
        !strcontains(aws_iam_role_policy.workload_range_participant_secrets["portal"].policy, "/raes/${kind}/")
      ])
    )
    error_message = "The portal may read only participant-delivery range secrets, never host-management or directory-admin secrets."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.workload_range_participant_secrets["portal"].policy).Statement[1].Resource == "arn:aws:kms:us-east-2:123456789012:key/mock-portal-secrets-manager" &&
      jsondecode(aws_iam_role_policy.workload_range_participant_secrets["portal"].policy).Statement[1].Condition.StringEquals["kms:ViaService"] == "secretsmanager.us-east-2.amazonaws.com" &&
      jsondecode(aws_iam_role_policy.workload_range_participant_secrets["portal"].policy).Statement[1].Condition.StringLike["kms:EncryptionContext:SecretARN"] == jsondecode(aws_iam_role_policy.workload_range_participant_secrets["portal"].policy).Statement[0].Resource
    )
    error_message = "Range-credential Decrypt must be confined to the key the provisioner encrypts with, via Secrets Manager, for exactly the participant-delivery secret ARNs."
  }

  # Platform application access (#2466): only opted-in Django identities, exact
  # portal-stack resources, KMS confined by service, metrics by namespace.
  assert {
    condition     = toset(keys(aws_iam_role_policy.workload_platform_application)) == toset(["portal", "workers"])
    error_message = "Platform application access must be granted only to identities that opt in."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[0].Resource == ["arn:aws:sqs:us-east-2:${data.aws_caller_identity.current.account_id}:test-portal-cms-tasks", "arn:aws:sqs:us-east-2:${data.aws_caller_identity.current.account_id}:test-portal-engine-tasks", "arn:aws:sqs:us-east-2:${data.aws_caller_identity.current.account_id}:test-portal-mc-tasks"] &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[1].Resource == "arn:aws:sns:us-east-2:${data.aws_caller_identity.current.account_id}:test-portal-range-events" &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[2].Resource == "arn:aws:kms:us-east-2:123456789012:key/mock-portal-messaging" &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[2].Condition.StringEquals["kms:ViaService"] == ["sqs.us-east-2.amazonaws.com", "sns.us-east-2.amazonaws.com"] &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[3].Resource == "arn:aws:s3:::test-storage-bucket/*" &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[4].Resource == "arn:aws:s3:::test-storage-bucket" &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[5].Resource == "arn:aws:kms:us-east-2:123456789012:key/mock-portal-storage" &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[5].Condition.StringEquals["kms:ViaService"] == "s3.us-east-2.amazonaws.com" &&
      jsondecode(aws_iam_role_policy.workload_platform_application["workers"].policy).Statement[6].Condition.StringEquals["cloudwatch:namespace"] == ["Shifter/PortalCapacity", "Shifter/WarmPool", "Shifter/CtfCommunication"]
    )
    error_message = "Platform application access must target exactly the portal-stack queues, topic, storage bucket and their keys, and the application metric namespaces."
  }

  # Isolated acquisition Job (#2463): only the opted-in identity, object get/put
  # under the delivery prefix only (no list, no delete), storage key via S3 only.
  assert {
    condition = (
      keys(aws_iam_role_policy.workload_feature_artifact_store) == ["artifactAcquirer"] &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store["artifactAcquirer"].policy).Statement[0].Action == ["s3:PutObject"] &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store["artifactAcquirer"].policy).Statement[0].Resource == "arn:aws:s3:::test-storage-bucket/raes/content-delivery/*" &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store["artifactAcquirer"].policy).Statement[1].Resource == "arn:aws:kms:us-east-2:123456789012:key/mock-portal-storage" &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store["artifactAcquirer"].policy).Statement[1].Condition.StringEquals["kms:ViaService"] == "s3.us-east-2.amazonaws.com" &&
      !contains(keys(aws_iam_role_policy.workload_platform_application), "artifactAcquirer") &&
      !contains(keys(aws_iam_role_policy.workload_rds_iam), "artifactAcquirer")
    )
    error_message = "The acquisition Job may only put objects under the delivery prefix, with no database or platform application access."
  }

  # Deploy content bootstrap checks inventoried artifacts exist: HEAD (s3:GetObject)
  # under the delivery prefix plus ListBucket for 404s, and no storage-key KMS grant.
  assert {
    condition = (
      keys(aws_iam_role_policy.workload_feature_artifact_store_read) == ["migrator"] &&
      length(jsondecode(aws_iam_role_policy.workload_feature_artifact_store_read["migrator"].policy).Statement) == 2 &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store_read["migrator"].policy).Statement[0].Action == ["s3:GetObject"] &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store_read["migrator"].policy).Statement[0].Resource == "arn:aws:s3:::test-storage-bucket/raes/content-delivery/*" &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store_read["migrator"].policy).Statement[1].Action == ["s3:ListBucket"] &&
      jsondecode(aws_iam_role_policy.workload_feature_artifact_store_read["migrator"].policy).Statement[1].Resource == "arn:aws:s3:::test-storage-bucket" &&
      !contains(keys(aws_iam_role_policy.workload_feature_artifact_store), "migrator") &&
      !contains(keys(aws_iam_role_policy.workload_platform_application), "migrator")
    )
    error_message = "The migrator may only check object existence under the delivery prefix, without decrypt or write access."
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
  # NetworkPolicies are actually enforced on EKS, not merely rendered. Mode is
  # "standard", not "strict": standard enforces every policy that selects a pod
  # (the chart's shifter-namespace default-deny applies in full) while leaving
  # unselected kube-system pods (coredns, CSI) reachable. strict default-denies
  # ALL pod traffic until an allow-policy exists, which severs coredns/CSI from
  # the API server and DNS cluster-wide. GKE Dataplane V2 parity likewise
  # default-allows pods no policy selects.
  assert {
    condition     = strcontains(aws_eks_addon.vpc_cni.configuration_values, "enableNetworkPolicy") && strcontains(aws_eks_addon.vpc_cni.configuration_values, "NETWORK_POLICY_ENFORCING_MODE") && strcontains(aws_eks_addon.vpc_cni.configuration_values, "standard")
    error_message = "The vpc-cni add-on must enable the NetworkPolicy agent in standard enforcement mode."
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

  # IP targets sit in the EKS-managed cluster security group; it carries the
  # exact cluster ownership tag so the controller's tag-scoped rule edits reach it.
  assert {
    condition = (
      aws_ec2_tag.cluster_security_group_lb_controller.resource_id == aws_eks_cluster.this.vpc_config[0].cluster_security_group_id &&
      aws_ec2_tag.cluster_security_group_lb_controller.key == "elbv2.k8s.aws/cluster" &&
      aws_ec2_tag.cluster_security_group_lb_controller.value == var.cluster_name
    )
    error_message = "The EKS cluster security group must carry the Load Balancer Controller's exact cluster ownership tag."
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


run "enabled_broker_routes" {
  command = apply
  variables {
    model_broker = {
      enabled                 = true
      hostname                = "models.example.test"
      admitted_subnets        = ["10.50.1.0/24"]
      tls_secret_name         = "broker-tls"
      control_tls_secret_name = "control-tls"
      trust_configmap_name    = "model-ca"
      invocation_models       = { primary = "anthropic.example-model-v1:0" }
    }
  }
  override_module {
    target = module.model_broker[0]
    outputs = {
      peering_id                 = "pcx-mock-broker"
      listener_security_group_id = "sg-mock-broker"
      deployment                 = null
    }
  }
  assert {
    condition = alltrue([for table in aws_route_table.private :
      length([for route in table.route : route if route.cidr_block == "10.50.0.0/16" && route.vpc_peering_connection_id == aws_vpc_peering_connection.range.id]) == 1
    ])
    error_message = "Every private EKS route table must return admitted guest traffic over the owned direct peering."
  }
  assert {
    condition = alltrue([for table in aws_route_table.private :
      length([for route in table.route : route if route.cidr_block == data.aws_vpc.portal.cidr_block && route.vpc_peering_connection_id == aws_vpc_peering_connection.portal.id]) == 1
    ])
    error_message = "Every private EKS route table must reach the portal data plane (RDS/Redis) over the portal peering."
  }
  assert {
    condition = alltrue([for table in aws_route_table.private :
      length([for route in table.route : route if route.cidr_block == data.aws_vpc.runner.cidr_block && route.vpc_peering_connection_id == aws_vpc_peering_connection.runner.id]) == 1
    ])
    error_message = "Every private EKS route table must return eks-deploy/smoke traffic to the runner VPC over the runner peering."
  }
  assert {
    condition = alltrue(flatten([for table in aws_route_table.private : [
      for route in table.route :
      (route.vpc_peering_connection_id == null || route.vpc_peering_connection_id == "") || route.cidr_block == "10.50.0.0/16" || route.cidr_block == data.aws_vpc.portal.cidr_block || route.cidr_block == data.aws_vpc.runner.cidr_block
    ]]))
    error_message = "Peering routes must stay bounded to the range + portal + runner CIDRs; the default route uses NAT."
  }
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.model_broker[0].referenced_security_group_id == "sg-mock-broker" &&
      aws_vpc_security_group_ingress_rule.model_broker[0].from_port == 8443 &&
      aws_vpc_security_group_ingress_rule.model_broker[0].to_port == 8443
    )
    error_message = "Only the model NLB security group may reach the broker's TLS target port."
  }
}

run "range_management_independent_of_optional_broker" {
  command = apply
  assert {
    condition     = !var.model_broker.enabled && length(aws_route.range_to_management) == 2 && aws_vpc_peering_connection.range.peer_vpc_id == "vpc-mock-range"
    error_message = "Native guest management must exist without a model broker."
  }
}
