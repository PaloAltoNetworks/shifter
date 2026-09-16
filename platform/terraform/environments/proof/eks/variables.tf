variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-2"
}

variable "deployment_role_arn" {
  description = "Protected deploy role granted EKS API access."
  type        = string
}

variable "domain_name" {
  description = "Public deployment hostname."
  type        = string
}

variable "edge_client_cidrs" {
  description = "Validated public source CIDRs allowed to reach HTTPS ingress."
  type        = list(string)

  validation {
    condition     = length(var.edge_client_cidrs) > 0
    error_message = "At least one explicit ingress source CIDR is required."
  }
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
}

variable "provider_api_cidrs" {
  description = "Validated CIDRs used by NetworkPolicy egress to AWS APIs."
  type        = list(string)

  validation {
    condition     = length(var.provider_api_cidrs) > 0
    error_message = "At least one explicit provider API CIDR is required."
  }
}

variable "runtime_env" {
  description = "Canonical non-secret runtime bindings and secret references projected into the shared chart."
  type        = map(string)
  sensitive   = true

  validation {
    condition = alltrue([
      for key in [
        "AWS_REGION",
        # ENGINE_TASK_* ECS coordinates are retired (#1826): the provisioner
        # dispatches as a Kubernetes Job. ENGINE_TASK_NAMESPACE and
        # ENGINE_TASK_SERVICE_ACCOUNT_NAME come from the chart; ENGINE_TASK_IMAGE
        # from the renderer; the range/portal provisioner env is assembled by
        # module.eks_provisioner_env, not supplied here.
        "OIDC_AUTH_DOMAIN",
        "OIDC_ISSUER_URL",
        "OIDC_RP_CLIENT_ID",
        "OIDC_SECRET_ID",
        "QUEUE_CMS_CONSUMER_ID",
        "QUEUE_CMS_PUBLISHER_ID",
        "QUEUE_ENGINE_CONSUMER_ID",
        "QUEUE_ENGINE_PUBLISHER_ID",
        "QUEUE_MC_CONSUMER_ID",
        "QUEUE_MC_PUBLISHER_ID",
        "RANGE_EVENTS_TOPIC_ID",
        "STORAGE_BUCKET_NAME",
      ] : try(length(trimspace(var.runtime_env[key])) > 0, false)
    ])
    error_message = "runtime_env must contain every canonical AWS platform runtime binding."
  }
}

variable "db_name" {
  description = "Portal control-plane database name the provisioner Job connects to (IAM auth)."
  type        = string
  default     = "shifter"
}

variable "dc_domain_name" {
  description = "Prebaked Windows DC domain name for the provisioner env (empty when no Windows DC scenario is deployed)."
  type        = string
  default     = ""
}

variable "provisioner_extra_env" {
  description = "Additional non-secret provisioner env (e.g. AWS_POLARIS_AGENT_* for AWS Polaris deployments)."
  type        = map(string)
  default     = {}
}

variable "ctf_content_bucket_arn" {
  description = "Optional private S3 bucket ARN holding digest-pinned native CTF content bundles."
  type        = string
  default     = ""
}

variable "ctf_content_prefix" {
  description = "Contained key prefix holding native CTF content bundles."
  type        = string
  default     = "ctf/content-bundles/"
}

variable "vpc_cidr" {
  description = "EKS-owned VPC CIDR."
  type        = string
  default     = "10.81.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones."
  type        = list(string)
  default     = ["us-east-2a", "us-east-2b"]
}

variable "private_subnet_cidrs" {
  description = "Private node/pod subnet CIDRs."
  type        = list(string)
  default     = ["10.81.0.0/20", "10.81.16.0/20"]
}

variable "public_subnet_cidrs" {
  description = "Public NAT/edge subnet CIDRs."
  type        = list(string)
  default     = ["10.81.128.0/24", "10.81.129.0/24"]
}

variable "kubernetes_version" {
  description = "Pinned EKS Kubernetes version."
  type        = string
  default     = "1.31"
}

variable "node_instance_types" {
  description = "Managed-node instance types."
  type        = list(string)
  default     = ["m7i.large"]
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

variable "oidc_thumbprints" {
  description = "EKS OIDC issuer trust-chain fingerprints."
  type        = list(string)
  default = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1b511abead59c6ce207077c0bf0e0043b1382612",
  ]
}

variable "tags" {
  description = "Additional tags."
  type        = map(string)
  default     = {}
}
