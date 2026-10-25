# Tenant source keys are created by the portal and projected only by the private
# control service. Neither broker nor participant roles gain secret-store access.
locals {
  model_source_secret_arn = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-model-source-*"
}

resource "aws_iam_role_policy" "model_source_credentials" {
  for_each = var.model_broker.enabled ? toset(["portal", "workers"]) : toset([])
  name     = "owned-model-source-credentials"
  role     = aws_iam_role.workload[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = each.key == "portal" ? [
        "secretsmanager:CreateSecret", "secretsmanager:TagResource", "secretsmanager:GetSecretValue", "secretsmanager:DeleteSecret"
      ] : ["secretsmanager:GetSecretValue"]
      Resource = [local.model_source_secret_arn]
    }]
  })
}
