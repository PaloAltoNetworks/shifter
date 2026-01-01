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

output "log_group_name" {
  description = "Name of the CloudWatch log group for pre-signup Lambda"
  value       = aws_cloudwatch_log_group.pre_signup.name
}
