output "portal_ecr_url" {
  description = "ECR repository URL for the portal"
  value       = module.portal_ecr.repository_url
}

output "portal_ecr_arn" {
  description = "ECR repository ARN for the portal"
  value       = module.portal_ecr.repository_arn
}

output "mcp_shifter_ecr_url" {
  description = "ECR repository URL for mcp-shifter"
  value       = module.mcp_shifter_ecr.repository_url
}

output "mcp_shifter_ecr_arn" {
  description = "ECR repository ARN for mcp-shifter"
  value       = module.mcp_shifter_ecr.repository_arn
}
