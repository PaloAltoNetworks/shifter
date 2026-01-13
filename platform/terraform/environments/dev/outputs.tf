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

# ------------------------------------------------------------------------------
# Guacamole ECR Outputs
# ------------------------------------------------------------------------------

output "guacd_ecr_url" {
  description = "ECR repository URL for guacd"
  value       = module.guacd_ecr.repository_url
}

output "guacd_ecr_arn" {
  description = "ECR repository ARN for guacd"
  value       = module.guacd_ecr.repository_arn
}

output "guacamole_client_ecr_url" {
  description = "ECR repository URL for guacamole-client"
  value       = module.guacamole_client_ecr.repository_url
}

output "guacamole_client_ecr_arn" {
  description = "ECR repository ARN for guacamole-client"
  value       = module.guacamole_client_ecr.repository_arn
}
