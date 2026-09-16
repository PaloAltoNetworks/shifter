terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  environment  = "prod"
  cluster_name = "shifter-${local.environment}-eks"
  secret_names = toset(["database", "django", "redis"])

  # The EKS control plane composes over the existing portal data plane
  # (ADR-044-R6): portal resources are named "${environment}-portal-*".
  portal_name_prefix       = "${local.environment}-portal"
  permissions_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shifter-${local.environment}-ci-role-boundary"
}

module "eks" {
  source = "../../../modules/portal/eks"

  environment              = local.environment
  aws_region               = var.aws_region
  cluster_name             = local.cluster_name
  deployment_role_arn      = var.deployment_role_arn
  permissions_boundary_arn = local.permissions_boundary_arn
  vpc_cidr                 = var.vpc_cidr
  availability_zones       = var.availability_zones
  private_subnet_cidrs     = var.private_subnet_cidrs
  public_subnet_cidrs      = var.public_subnet_cidrs
  kubernetes_version       = var.kubernetes_version
  addon_versions           = var.addon_versions
  node_instance_types      = var.node_instance_types
  node_desired_size        = var.node_desired_size
  node_min_size            = var.node_min_size
  node_max_size            = var.node_max_size
  domain_name              = var.domain_name
  oidc_thumbprints         = var.oidc_thumbprints
  secret_names             = local.secret_names
  workload_identities = {
    cni = {
      namespace       = "kube-system"
      service_account = "aws-node"
      policy_arns     = ["arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"]
      secret_names    = []
    }
    ingress = {
      namespace       = "kube-system"
      service_account = "aws-load-balancer-controller"
      policy_arns     = []
      secret_names    = []
    }
    portal = {
      namespace       = "shifter-platform"
      service_account = "portal"
      policy_arns     = []
      secret_names    = local.secret_names
      object_read_arns = (
        var.ctf_content_bucket_arn == ""
        ? []
        : ["${var.ctf_content_bucket_arn}/${var.ctf_content_prefix}*"]
      )
    }
    workers = {
      namespace       = "shifter-platform"
      service_account = "workers"
      policy_arns     = []
      secret_names    = local.secret_names
    }
    ctfScheduler = {
      namespace       = "shifter-platform"
      service_account = "ctf-scheduler"
      policy_arns     = []
      secret_names    = local.secret_names
    }
    # Dedicated provisioner Job launcher + the privileged provisioner Job (#1826).
    # The provisioner's range-provisioning permission set is attached separately
    # by module.provisioner_iam (shared with the ECS task role); these entries
    # create the exact-subject IRSA roles and grant platform secret access.
    provisionerLauncher = {
      namespace       = "shifter-platform"
      service_account = "provisioner-launcher"
      policy_arns     = []
      secret_names    = local.secret_names
    }
    provisioner = {
      namespace       = "shifter-jobs"
      service_account = "provisioner"
      policy_arns     = []
      secret_names    = local.secret_names
    }
    # EKS add-on controller identities (#1826). AWS-managed CSI driver policies;
    # controllers run in kube-system with their driver-default service accounts.
    ebs-csi = {
      namespace       = "kube-system"
      service_account = "ebs-csi-controller-sa"
      policy_arns     = ["arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"]
      secret_names    = []
    }
    efs-csi = {
      namespace       = "kube-system"
      service_account = "efs-csi-controller-sa"
      policy_arns     = ["arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy"]
      secret_names    = []
    }
  }

  tags = merge(var.tags, {
    Environment = local.environment
    ManagedBy   = "terraform"
    Project     = "shifter"
    Substrate   = "eks"
  })
}

# Compose the provisioner Job environment over the existing portal + range data
# plane (ADR-044-R6) and attach the shared provisioner permission set to the
# provisioner IRSA role.
module "eks_provisioner_env" {
  source = "../../../modules/portal/eks-provisioner-env"

  environment              = local.environment
  name_prefix              = local.portal_name_prefix
  runtime_env              = var.runtime_env
  provisioner_role_name    = module.eks.workload_role_names["provisioner"]
  provisioner_role_id      = module.eks.workload_role_ids["provisioner"]
  permissions_boundary_arn = local.permissions_boundary_arn
  storage_bucket_name      = var.runtime_env["STORAGE_BUCKET_NAME"]
  db_name                  = var.db_name
  dc_domain_name           = var.dc_domain_name
  extra_env                = var.provisioner_extra_env

  tags = merge(var.tags, {
    Environment = local.environment
    ManagedBy   = "terraform"
    Project     = "shifter"
    Substrate   = "eks"
  })
}
