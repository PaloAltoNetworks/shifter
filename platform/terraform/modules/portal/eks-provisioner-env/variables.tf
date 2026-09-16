variable "environment" {
  description = "Deployment environment (dev, prod, proof)."
  type        = string
}

variable "name_prefix" {
  description = "Portal resource name prefix (e.g. dev-portal); selects the portal RDS/KMS/VPC the provisioner shares."
  type        = string
}

variable "runtime_env" {
  description = "Management-plane runtime bindings from the deploy tooling (OIDC, queues, storage). Merged under the assembled provisioner env."
  type        = map(string)
  sensitive   = true
}

variable "provisioner_role_name" {
  description = "Name of the EKS provisioner IRSA role (aws_iam_role.workload[\"provisioner\"])."
  type        = string
}

variable "provisioner_role_id" {
  description = "Id of the EKS provisioner IRSA role, for inline-policy attachment."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary applied to provisioner-created range/VPN gateway roles."
  type        = string
}

variable "storage_bucket_name" {
  description = "Name of the shared portal S3 bucket used as the range agent/bootstrap bucket."
  type        = string
}

variable "db_name" {
  description = "Portal control-plane database name the provisioner connects to."
  type        = string
}

variable "dc_domain_name" {
  description = "Prebaked Windows DC domain name (empty when no Windows DC scenario is deployed)."
  type        = string
  default     = ""
}

variable "kali_instance_type" {
  description = "EC2 instance type for provisioned Kali attacker hosts."
  type        = string
  default     = "t3.medium"
}

variable "victim_instance_type" {
  description = "EC2 instance type for provisioned victim hosts."
  type        = string
  default     = "t3.small"
}

variable "extra_env" {
  description = "Additional non-secret provisioner env (e.g. AWS_POLARIS_AGENT_* when the deployment runs AWS Polaris). Merged last."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Common resource tags."
  type        = map(string)
  default     = {}
}
