# ------------------------------------------------------------------------------
# Cognito User Pool
# ------------------------------------------------------------------------------

resource "aws_cognito_user_pool" "main" {
  name = "${var.name_prefix}-users"

  # Email as username
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Password policy
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # MFA required
  mfa_configuration = "ON"

  software_token_mfa_configuration {
    enabled = true
  }

  # Account recovery via email
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Email verification
  verification_message_template {
    default_email_option = "CONFIRM_WITH_CODE"
    email_subject        = "Shifter Portal - Verify your email"
    email_message        = "Your verification code is {####}"
  }

  # Schema - email required
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = true
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 5
      max_length = 254
    }
  }

  # Lambda triggers
  lambda_config {
    pre_sign_up = aws_lambda_function.pre_signup.arn
  }

  # Deletion protection
  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  tags = var.tags
}

# ------------------------------------------------------------------------------
# User Pool Domain (Hosted UI)
# ------------------------------------------------------------------------------

resource "aws_cognito_user_pool_domain" "main" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.main.id
}

# ------------------------------------------------------------------------------
# User Pool Client
# ------------------------------------------------------------------------------

resource "aws_cognito_user_pool_client" "portal" {
  name         = "${var.name_prefix}-portal-client"
  user_pool_id = aws_cognito_user_pool.main.id

  # OIDC settings
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  # Callback URLs
  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

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
# User Pool Client - AgentChat (OpenWebUI)
# ------------------------------------------------------------------------------

resource "aws_cognito_user_pool_client" "agentchat" {
  count = length(var.agentchat_callback_urls) > 0 ? 1 : 0

  name         = "${var.name_prefix}-agentchat-client"
  user_pool_id = aws_cognito_user_pool.main.id

  # OIDC settings
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  # Callback URLs
  callback_urls = var.agentchat_callback_urls
  logout_urls   = var.agentchat_logout_urls

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
# Pre-Signup Lambda
# ------------------------------------------------------------------------------

data "archive_file" "pre_signup" {
  type        = "zip"
  source_file = "${path.module}/lambda/pre_signup.py"
  output_path = "${path.module}/lambda/pre_signup.zip"
}

resource "aws_lambda_function" "pre_signup" {
  function_name    = "${var.name_prefix}-cognito-pre-signup"
  filename         = data.archive_file.pre_signup.output_path
  source_code_hash = data.archive_file.pre_signup.output_base64sha256
  handler          = "pre_signup.handler"
  runtime          = "python3.12"
  timeout          = 5
  memory_size      = 128

  role = aws_iam_role.lambda_exec.arn

  environment {
    variables = {
      ALLOWED_DOMAINS = join(",", var.allowed_email_domains)
      ALLOWED_EMAILS  = join(",", var.allowed_emails)
    }
  }

  tags = var.tags
}

resource "aws_lambda_permission" "cognito_invoke" {
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pre_signup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}

# ------------------------------------------------------------------------------
# Lambda IAM Role
# ------------------------------------------------------------------------------

resource "aws_iam_role" "lambda_exec" {
  name = "${var.name_prefix}-cognito-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ------------------------------------------------------------------------------
# Store client secret in Secrets Manager
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_149:Deferred for MVP. AWS-managed keys sufficient for low-usage internal MVP. See #213
resource "aws_secretsmanager_secret" "cognito_client" {
  name                    = "shifter-${var.name_prefix}-cognito"
  description             = "Cognito client credentials"
  recovery_window_in_days = 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "cognito_client" {
  secret_id = aws_secretsmanager_secret.cognito_client.id
  secret_string = jsonencode({
    client_id     = aws_cognito_user_pool_client.portal.id
    client_secret = aws_cognito_user_pool_client.portal.client_secret
    user_pool_id  = aws_cognito_user_pool.main.id
    domain        = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
    issuer_url    = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  })
}

# ------------------------------------------------------------------------------
# Store AgentChat client secret in Secrets Manager
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_149:Deferred for MVP. AWS-managed keys sufficient for low-usage internal MVP. See #213
resource "aws_secretsmanager_secret" "agentchat_client" {
  count = length(var.agentchat_callback_urls) > 0 ? 1 : 0

  name                    = "shifter-${var.name_prefix}-cognito-agentchat"
  description             = "Cognito client credentials for AgentChat (OpenWebUI)"
  recovery_window_in_days = 0

  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "agentchat_client" {
  count = length(var.agentchat_callback_urls) > 0 ? 1 : 0

  secret_id = aws_secretsmanager_secret.agentchat_client[0].id
  secret_string = jsonencode({
    client_id     = aws_cognito_user_pool_client.agentchat[0].id
    client_secret = aws_cognito_user_pool_client.agentchat[0].client_secret
    user_pool_id  = aws_cognito_user_pool.main.id
    domain        = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
    issuer_url    = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  })
}
