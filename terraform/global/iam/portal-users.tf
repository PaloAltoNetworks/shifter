# Portal IAM User
#
# Dedicated user for portal container to access Secrets Manager in prod.
# Credentials passed as environment variables via GitHub Secrets.
# Local dev uses docker-compose with local Postgres - no AWS needed.

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

output "portal_prod_access_key_id" {
  description = "Access key ID for portal prod user"
  value       = aws_iam_access_key.portal_prod.id
}

output "portal_prod_secret_access_key" {
  description = "Secret access key for portal prod user"
  value       = aws_iam_access_key.portal_prod.secret
  sensitive   = true
}
