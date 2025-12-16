# Cognito App Client for OpenWebUI
# This contract defines the Cognito configuration required for OpenWebUI SSO

resource "aws_cognito_user_pool_client" "openwebui" {
  name         = "${var.name_prefix}-openwebui"
  user_pool_id = aws_cognito_user_pool.main.id

  # OAuth settings
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  # Callback URLs
  callback_urls = [
    "https://${var.domain}/chat/oauth/oidc/callback"
  ]
  logout_urls = [
    "https://${var.domain}/chat"
  ]

  # Identity providers
  supported_identity_providers = ["COGNITO"]

  # Token validity
  access_token_validity  = 1   # hours
  id_token_validity      = 1   # hours
  refresh_token_validity = 30  # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent token revocation on user attribute updates
  prevent_user_existence_errors = "ENABLED"

  # Read/write attributes
  read_attributes  = ["email", "email_verified", "name"]
  write_attributes = ["email", "name"]
}

# Store client secret in Secrets Manager for OpenWebUI configuration
resource "aws_secretsmanager_secret" "openwebui_oauth" {
  name        = "${var.name_prefix}/openwebui/oauth-client-secret"
  description = "OAuth client secret for OpenWebUI Cognito integration"
}

resource "aws_secretsmanager_secret_version" "openwebui_oauth" {
  secret_id = aws_secretsmanager_secret.openwebui_oauth.id
  secret_string = jsonencode({
    client_id     = aws_cognito_user_pool_client.openwebui.id
    client_secret = aws_cognito_user_pool_client.openwebui.client_secret
  })
}

# Outputs for OpenWebUI configuration
output "openwebui_cognito_client_id" {
  value       = aws_cognito_user_pool_client.openwebui.id
  description = "Cognito client ID for OpenWebUI"
}

output "openwebui_oauth_secret_arn" {
  value       = aws_secretsmanager_secret.openwebui_oauth.arn
  description = "Secrets Manager ARN containing OAuth credentials"
}
