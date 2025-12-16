# Cursor Agent IAM User for AWS Bedrock
#
# Creates an IAM user with access keys for Cursor IDE Bedrock access.
# See: https://cursor.com/docs/settings/aws-bedrock
#
# NOTE: Access keys are output as sensitive values.
# Retrieve with: terraform output -raw cursor_bedrock_secret_access_key

# IAM User for Cursor Bedrock access
resource "aws_iam_user" "cursor_bedrock" {
  name = "cursor-bedrock-agent"
  path = "/service-accounts/"

  tags = {
    Name        = "cursor-bedrock-agent"
    Project     = "shifter"
    Environment = var.environment
    Purpose     = "Cursor IDE Bedrock access"
  }
}

# Access key for the user
resource "aws_iam_access_key" "cursor_bedrock" {
  user = aws_iam_user.cursor_bedrock.name
}

# Policy granting Bedrock model invocation
# Matches permissions from agentchat/ec2 module
resource "aws_iam_user_policy" "cursor_bedrock_invoke" {
  name = "bedrock-invoke-models"
  user = aws_iam_user.cursor_bedrock.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvokeModels"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
          "arn:aws:bedrock:*::foundation-model/deepseek.*",
          "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-*",
          "arn:aws:bedrock:*:*:inference-profile/global.anthropic.claude-*",
          "arn:aws:bedrock:*:*:inference-profile/us.deepseek.*"
        ]
      },
      {
        Sid    = "BedrockListModels"
        Effect = "Allow"
        Action = [
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel",
          "bedrock:ListInferenceProfiles",
          "bedrock:GetInferenceProfile"
        ]
        Resource = "*"
      }
    ]
  })
}

output "cursor_bedrock_access_key_id" {
  description = "Access Key ID for Cursor Bedrock configuration"
  value       = aws_iam_access_key.cursor_bedrock.id
}

output "cursor_bedrock_secret_access_key" {
  description = "Secret Access Key for Cursor Bedrock configuration"
  value       = aws_iam_access_key.cursor_bedrock.secret
  sensitive   = true
}

output "cursor_bedrock_setup_instructions" {
  description = "Setup instructions for Cursor"
  value       = <<-EOT
    1. Go to Cursor Settings > Models > AWS Bedrock
    2. Enter Access Key ID: ${aws_iam_access_key.cursor_bedrock.id}
    3. Get Secret: terraform output -raw cursor_bedrock_secret_access_key
    4. Enter Region: us-east-2
    5. Click Validate & Save
  EOT
}
