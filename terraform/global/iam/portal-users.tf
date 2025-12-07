# Portal IAM Users
#
# Dedicated users for portal container to access Secrets Manager.
# Credentials passed as environment variables - works in local dev and prod.

# ------------------------------------------------------------------------------
# Dev User
# ------------------------------------------------------------------------------

resource "aws_iam_user" "portal_dev" {
  name = "shifter-portal-dev"
  path = "/shifter/"

  tags = {
    Project     = "shifter"
    Environment = "dev"
    Purpose     = "Portal container secrets access"
  }
}

resource "aws_iam_user_policy" "portal_dev_secrets" {
  name = "secrets-read"
  user = aws_iam_user.portal_dev.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadDevSecrets"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-dev-portal-*"
      }
    ]
  })
}

resource "aws_iam_access_key" "portal_dev" {
  user = aws_iam_user.portal_dev.name
}

# ------------------------------------------------------------------------------
# Prod User
# ------------------------------------------------------------------------------

resource "aws_iam_user" "portal_prod" {
  name = "shifter-portal-prod"
  path = "/shifter/"

  tags = {
    Project     = "shifter"
    Environment = "prod"
    Purpose     = "Portal container secrets access"
  }
}

resource "aws_iam_user_policy" "portal_prod_secrets" {
  name = "secrets-read"
  user = aws_iam_user.portal_prod.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadProdSecrets"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-prod-portal-*"
      }
    ]
  })
}

resource "aws_iam_access_key" "portal_prod" {
  user = aws_iam_user.portal_prod.name
}

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "portal_dev_access_key_id" {
  description = "Access key ID for portal dev user"
  value       = aws_iam_access_key.portal_dev.id
}

output "portal_dev_secret_access_key" {
  description = "Secret access key for portal dev user"
  value       = aws_iam_access_key.portal_dev.secret
  sensitive   = true
}

output "portal_prod_access_key_id" {
  description = "Access key ID for portal prod user"
  value       = aws_iam_access_key.portal_prod.id
}

output "portal_prod_secret_access_key" {
  description = "Secret access key for portal prod user"
  value       = aws_iam_access_key.portal_prod.secret
  sensitive   = true
}
