output "portal_ecr_url" {
  description = "ECR repository URL for the portal"
  value       = module.portal_ecr.repository_url
}

output "portal_ecr_arn" {
  description = "ECR repository ARN for the portal"
  value       = module.portal_ecr.repository_arn
}

# ------------------------------------------------------------------------------
# Pulumi Provisioner ECR Outputs
# ------------------------------------------------------------------------------

output "pulumi_provisioner_ecr_url" {
  description = "ECR repository URL for the Pulumi provisioner"
  value       = module.pulumi_provisioner_ecr.repository_url
}

output "pulumi_provisioner_ecr_arn" {
  description = "ECR repository ARN for the Pulumi provisioner"
  value       = module.pulumi_provisioner_ecr.repository_arn
}
