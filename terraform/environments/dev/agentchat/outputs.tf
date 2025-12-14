output "instance_id" {
  description = "AgentChat EC2 instance ID"
  value       = module.ec2.instance_id
}

output "private_ip" {
  description = "AgentChat EC2 private IP"
  value       = module.ec2.private_ip
}

output "security_group_id" {
  description = "AgentChat EC2 security group ID"
  value       = module.ec2.security_group_id
}

# ------------------------------------------------------------------------------
# OpenWebUI OIDC Configuration
# ------------------------------------------------------------------------------

output "openwebui_oidc_provider_url" {
  description = "OIDC provider URL for OpenWebUI (Cognito issuer)"
  value       = data.terraform_remote_state.portal.outputs.cognito_issuer_url
}

output "openwebui_oidc_client_id" {
  description = "OIDC client ID for OpenWebUI"
  value       = data.terraform_remote_state.portal.outputs.agentchat_cognito_client_id
}

output "openwebui_oidc_secret_arn" {
  description = "ARN of Secrets Manager secret containing OIDC credentials"
  value       = data.terraform_remote_state.portal.outputs.agentchat_cognito_secret_arn
}

output "openwebui_cognito_domain" {
  description = "Cognito hosted UI domain for OpenWebUI"
  value       = data.terraform_remote_state.portal.outputs.cognito_domain
}

# ------------------------------------------------------------------------------
# VPC Peering
# ------------------------------------------------------------------------------

output "vpc_peering_connection_id" {
  description = "VPC peering connection ID between Portal and Range VPCs"
  value       = aws_vpc_peering_connection.portal_to_range.id
}
