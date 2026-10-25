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
  environment  = "dev"
  cluster_name = "shifter-${local.environment}-eks"
  secret_names = toset(["database", "django", "redis", "cognito", "guacamole-db", "guacamole-json-auth"])

  # The EKS control plane composes over the existing portal data plane
  # (ADR-044-R6): portal resources are named "${environment}-portal-*".
  portal_name_prefix       = "${local.environment}-portal"
  permissions_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shifter-${local.environment}-ci-role-boundary"
}

module "eks" {
  source = "../../../modules/portal/eks"

  model_broker = var.model_broker

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
  storage_bucket_name      = var.runtime_env["STORAGE_BUCKET_NAME"]
  # Exclusive gVisor pool for tenant runtime-plugin workers (#2526); the
  # nodePoolLabeler identity below applies its trusted pool label.
  enable_runtime_plugins = true
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
      # Broker participant SSH/RDP connections to realized range guests (#1826).
      range_participant_secret_read = true
      rds_iam_db_user               = "portal_runtime"
      object_read_arns = (
        var.ctf_content_bucket_arn == ""
        ? []
        : ["${var.ctf_content_bucket_arn}/${var.ctf_content_prefix}*"]
      )
      # SQS/SNS/storage/metrics for the platform application (#2466).
      platform_application_access = true
    }
    workers = {
      namespace       = "shifter-platform"
      service_account = "workers"
      policy_arns     = []
      secret_names    = local.secret_names
      rds_iam_db_user = "portal_runtime"
      # SQS/SNS/storage/metrics for the platform application (#2466).
      platform_application_access = true
    }
    ctfScheduler = {
      namespace       = "shifter-platform"
      service_account = "ctf-scheduler"
      policy_arns     = []
      secret_names    = local.secret_names
      rds_iam_db_user = "portal_runtime"
      # SQS/SNS/storage/metrics for the platform application (#2466).
      platform_application_access = true
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
      rds_iam_db_user = "portal_runtime"
      # SQS/SNS/storage/metrics for the platform application (#2466).
      platform_application_access = true
    }
    provisioner = {
      namespace       = "shifter-jobs"
      service_account = "provisioner"
      policy_arns     = []
      secret_names    = local.secret_names
    }
    # Isolated feature-artifact acquisition Job (ADR-034-R12, #2463): public HTTPS
    # egress, no database access, write-only to the content-addressed delivery
    # prefix. Its presence enables acquisition for this environment.
    artifactAcquirer = {
      namespace                    = "shifter-acquisition"
      service_account              = "artifact-acquirer"
      policy_arns                  = []
      secret_names                 = []
      feature_artifact_store_write = true
    }
    # Trusted runtime-plugin node-pool labeler (#2526): labels only nodes backed
    # by the plugin pool's node role. No secrets, no database.
    nodePoolLabeler = {
      namespace         = "shifter-platform"
      service_account   = "node-pool-labeler"
      policy_arns       = []
      secret_names      = []
      node_pool_labeler = true
    }
    # One-shot schema-migration + content-bootstrap Job (AWS EKS parity with the GCP
    # platform-migrate Job, #1826). aws_eks.py runs it once before the chart install so
    # the workloads deploy with SKIP_MIGRATIONS=1 and never race per-pod migrations on
    # startup (the provisioner-launcher's slow per-pod migration tripped its liveness
    # probe). entrypoint.sh hydrates the master (database) + app (django) + cognito
    # secrets to import settings and migrate as the master user, then switches to
    # portal_runtime RDS IAM auth for bootstrap_inbox_catalog / seed_raes_image_registry.
    migrator = {
      namespace       = "shifter-platform"
      service_account = "migrator"
      policy_arns     = []
      secret_names    = local.secret_names
      rds_iam_db_user = "portal_runtime"
      # acquire_feature_artifacts verifies inventoried artifacts still exist.
      feature_artifact_store_read = true
    }
    # One-shot guacamole database/role provisioner (AWS EKS parity with the GCP
    # cloud-sql module). RDS has no native terraform user/database resource and the
    # deploy runner cannot reach RDS, so aws_eks.py runs provision_guacamole_database
    # as a Job under this exact-subject identity before the chart install; it reads
    # the master (database), app (django) and guacamole-db secrets to create the
    # guacamole_admin role + guacamole database. It connects as the RDS master via
    # password, so it needs no rds_iam_db_user grant.
    guacamoleProvisioner = {
      namespace       = "shifter-platform"
      service_account = "guacamole-db-provisioner"
      policy_arns     = []
      # The provision command reads only the RDS master (database) and guacamole-db
      # credentials from Secrets Manager; it runs under ENVIRONMENT=build so Django
      # settings load without the other platform secrets.
      secret_names = toset(["database", "guacamole-db"])
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
