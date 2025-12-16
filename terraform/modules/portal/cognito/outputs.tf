output "user_pool_id" {
  description = "Cognito user pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "Cognito user pool ARN"
  value       = aws_cognito_user_pool.main.arn
}

output "client_id" {
  description = "Cognito user pool client ID"
  value       = aws_cognito_user_pool_client.portal.id
}

output "cognito_domain" {
  description = "Cognito hosted UI domain"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
}

output "issuer_url" {
  description = "OIDC issuer URL"
  value       = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

output "cognito_secret_arn" {
  description = "ARN of Secrets Manager secret containing Cognito credentials"
  value       = aws_secretsmanager_secret.cognito_client.arn
}

output "lambda_function_arn" {
  description = "ARN of pre-signup Lambda function"
  value       = aws_lambda_function.pre_signup.arn
}

# ------------------------------------------------------------------------------
# AgentChat (OpenWebUI) Client Outputs
# ------------------------------------------------------------------------------

output "agentchat_client_id" {
  description = "Cognito user pool client ID for AgentChat"
  value       = length(aws_cognito_user_pool_client.agentchat) > 0 ? aws_cognito_user_pool_client.agentchat[0].id : null
}

output "agentchat_secret_arn" {
  description = "ARN of Secrets Manager secret containing AgentChat Cognito credentials"
  value       = length(aws_secretsmanager_secret.agentchat_client) > 0 ? aws_secretsmanager_secret.agentchat_client[0].arn : null
}
