variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "aws_region" {
  description = "AWS region in which the EKS bundle is created."
  type        = string
}

variable "cluster_name" {
  description = "Name of the EKS cluster."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9-]{0,22}$", var.cluster_name))
    error_message = "cluster_name must be at most 23 alphanumeric-or-hyphen characters so the owned ALB name remains valid."
  }
}

variable "deployment_role_arn" {
  description = "Protected operator role granted short-lived EKS API access."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/.+", var.deployment_role_arn))
    error_message = "deployment_role_arn must be an IAM role ARN."
  }
}

variable "permissions_boundary_arn" {
  description = "Installation CI permissions boundary applied to every IAM role created by this module."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:policy/shifter-[A-Za-z0-9+=,.@_/-]+-ci-role-boundary$", var.permissions_boundary_arn))
    error_message = "permissions_boundary_arn must be the installation shifter-* CI role-boundary policy ARN."
  }
}

variable "vpc_cidr" {
  description = "CIDR for the EKS-owned VPC."
  type        = string
}

variable "availability_zones" {
  description = "Availability zones used for the EKS VPC."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2 && length(distinct(var.availability_zones)) == length(var.availability_zones)
    error_message = "At least two distinct availability zones are required."
  }
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs, ordered to match availability_zones."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_cidrs) == length(var.availability_zones)
    error_message = "private_subnet_cidrs must contain one CIDR per availability zone."
  }
}

variable "public_subnet_cidrs" {
  description = "Public NAT/edge subnet CIDRs, ordered to match availability_zones."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) == length(var.availability_zones)
    error_message = "public_subnet_cidrs must contain one CIDR per availability zone."
  }
}

variable "kubernetes_version" {
  description = "Pinned Kubernetes control-plane version."
  type        = string
}

variable "addon_versions" {
  description = "Reviewed EKS add-on versions compatible with kubernetes_version."
  type = object({
    vpc_cni           = string
    ebs_csi           = string
    efs_csi           = string
    coredns           = string
    kube_proxy        = string
    secrets_store_csi = string
  })

  validation {
    condition = alltrue([
      for version in values(var.addon_versions) :
      can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+-eksbuild\\.[0-9]+$", version))
    ])
    error_message = "Every EKS add-on version must be an explicit vX.Y.Z-eksbuild.N release."
  }
}

variable "node_instance_types" {
  description = "Allowed instance types for the managed private node group."
  type        = list(string)
}

variable "node_desired_size" {
  description = "Desired managed-node count."
  type        = number
  default     = 2
}

variable "node_min_size" {
  description = "Minimum managed-node count."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum managed-node count."
  type        = number
  default     = 4
}

variable "node_disk_size" {
  description = "Encrypted managed-node root disk size in GiB."
  type        = number
  default     = 80
}

variable "log_retention_days" {
  description = "Retention for EKS control-plane logs."
  type        = number
  default     = 365

  validation {
    condition     = var.log_retention_days >= 365
    error_message = "EKS control-plane logs must be retained for at least 365 days."
  }

}

variable "domain_name" {
  description = "Deployment hostname for the regional ACM certificate."
  type        = string
}

variable "oidc_thumbprints" {
  description = "SHA-1 fingerprints for the EKS OIDC issuer trust chain."
  type        = list(string)

  validation {
    condition     = length(var.oidc_thumbprints) > 0 && alltrue([for fingerprint in var.oidc_thumbprints : can(regex("^[0-9a-fA-F]{40}$", fingerprint))])
    error_message = "At least one 40-character SHA-1 OIDC thumbprint is required."
  }
}

variable "workload_identities" {
  description = "Per-process IRSA identities. Each map entry creates a distinct role bound to one exact namespace/service-account subject."
  type = map(object({
    namespace        = string
    service_account  = string
    policy_arns      = optional(set(string), [])
    secret_names     = optional(set(string), [])
    object_read_arns = optional(set(string), [])
  }))

  validation {
    condition = alltrue([
      for identity in values(var.workload_identities) :
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", identity.namespace)) &&
      can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", identity.service_account))
    ])
    error_message = "Workload identity namespaces and service accounts must be exact DNS-label names; wildcards are forbidden."
  }

  validation {
    condition = (
      contains(keys(var.workload_identities), "cni") &&
      var.workload_identities["cni"].namespace == "kube-system" &&
      var.workload_identities["cni"].service_account == "aws-node"
    )
    error_message = "workload_identities must bind cni to the exact kube-system/aws-node service account so CNI permissions are not placed on the node role."
  }

  validation {
    condition = (
      contains(keys(var.workload_identities), "ingress") &&
      var.workload_identities["ingress"].namespace == "kube-system" &&
      var.workload_identities["ingress"].service_account == "aws-load-balancer-controller"
    )
    error_message = "workload_identities must bind ingress to the exact kube-system/aws-load-balancer-controller service account."
  }
}

variable "secret_names" {
  description = "Names of encrypted Secrets Manager containers. Secret payloads are populated out of band."
  type        = set(string)

  validation {
    condition     = alltrue([for name in var.secret_names : can(regex("^[A-Za-z0-9/_+=.@-]+$", name))])
    error_message = "Secret names may contain only AWS Secrets Manager name characters."
  }
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
}
