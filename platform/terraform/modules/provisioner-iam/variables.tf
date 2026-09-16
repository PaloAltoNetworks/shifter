variable "name_prefix" {
  description = "Prefix for provisioner IAM policy names. Distinct per substrate so the ECS task-role and EKS IRSA-role policy sets never collide in one account."
  type        = string
}

variable "environment" {
  description = "Deployment environment; scopes the runtime resource-tag and namespace conditions on the provisioner permissions."
  type        = string
}

variable "role_name" {
  description = "Name of the IAM role the provisioner permissions attach to (the ECS task role or the EKS provisioner IRSA role)."
  type        = string
}

variable "role_id" {
  description = "ID of the IAM role the inline provisioner permissions attach to."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Installation permissions boundary the provisioner must set on every per-range role it creates (Polaris agent, VPN gateway)."
  type        = string
}

variable "engine_state_bucket_arn" {
  description = "ARN of the Pulumi/Terraform engine state S3 bucket."
  type        = string
}

variable "engine_locks_table_arn" {
  description = "ARN of the engine state-lock DynamoDB table."
  type        = string
}

variable "engine_secrets_kms_key_arn" {
  description = "ARN of the dedicated CMK the engine's awskms:// secrets provider uses."
  type        = string
}

variable "secrets_manager_kms_key_arn" {
  description = "ARN of the portal Secrets Manager CMK the provisioner decrypts secrets through."
  type        = string
}

variable "db_resource_id" {
  description = "RDS DbiResourceId used to scope the rds-db:connect grant for the provisioner_lambda DB user."
  type        = string
}

variable "agent_s3_bucket_arn" {
  description = "ARN of the agent/NGFW-bootstrap S3 bucket."
  type        = string
}

variable "range_vpc_id" {
  description = "Range VPC id used to scope RunInstances dependent-network authorizations."
  type        = string
}

variable "range_availability_zone" {
  description = "Range availability zone used to scope RunInstances root-volume creation."
  type        = string
}

variable "range_instance_role_arn" {
  description = "Shared range-host instance role ARN the provisioner may PassRole to EC2."
  type        = string
}

variable "ngfw_instance_role_arn" {
  description = "NGFW instance role ARN the provisioner may PassRole to EC2 (empty when NGFW is disabled)."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Common tags applied to the created managed policies."
  type        = map(string)
  default     = {}
}
