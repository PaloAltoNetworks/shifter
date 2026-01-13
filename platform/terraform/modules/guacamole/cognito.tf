# ------------------------------------------------------------------------------
# Cognito App Client for Guacamole OIDC Authentication
# ------------------------------------------------------------------------------
# Creates a dedicated Cognito app client for Guacamole when OIDC is enabled.
# This keeps Guacamole's authentication separate from Portal's app client.

resource "aws_cognito_user_pool_client" "guacamole" {
  count = var.enable_oidc ? 1 : 0

  name         = "${var.name_prefix}-guacamole-client"
  user_pool_id = var.cognito_user_pool_id

  # OIDC settings - Guacamole requires implicit flow for OIDC
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code", "implicit"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  # Callback URLs - Guacamole's OIDC callback path
  callback_urls = ["https://${var.domain_name}/guacamole/"]
  logout_urls   = ["https://${var.domain_name}/guacamole/"]

  # Token validity
  access_token_validity  = 1  # hours
  id_token_validity      = 1  # hours
  refresh_token_validity = 30 # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent user existence errors (security)
  prevent_user_existence_errors = "ENABLED"

  # Read attributes
  read_attributes = ["email", "email_verified"]

  # Write attributes
  write_attributes = ["email"]
}

# ------------------------------------------------------------------------------
# Local values for OIDC configuration
# ------------------------------------------------------------------------------

locals {
  # Construct OIDC endpoints from Cognito configuration
  oidc_authorization_endpoint = var.enable_oidc ? "${var.cognito_domain}/oauth2/authorize" : ""
  oidc_jwks_endpoint          = var.enable_oidc ? "https://cognito-idp.${var.aws_region}.amazonaws.com/${var.cognito_user_pool_id}/.well-known/jwks.json" : ""
  oidc_issuer_url             = var.enable_oidc ? "https://cognito-idp.${var.aws_region}.amazonaws.com/${var.cognito_user_pool_id}" : ""
  oidc_client_id              = var.enable_oidc ? aws_cognito_user_pool_client.guacamole[0].id : ""
  oidc_redirect_uri           = var.enable_oidc ? "https://${var.domain_name}/guacamole/" : ""
}
