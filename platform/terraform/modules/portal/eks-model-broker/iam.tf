locals {
  model_arns = { for name, model in var.settings.invocation_models : name => "arn:aws:bedrock:${var.region}::foundation-model/${model}" }
}

resource "aws_iam_role" "broker" {
  name                 = "${var.cluster_name}-model-broker"
  permissions_boundary = var.permissions_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = var.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringEquals = {
        "${trimprefix(var.oidc_issuer, "https://")}:aud" = "sts.amazonaws.com"
        "${trimprefix(var.oidc_issuer, "https://")}:sub" = "system:serviceaccount:shifter-platform:model-broker"
      } }
    }]
  })
  tags = var.tags
}

resource "aws_iam_role" "invocation" {
  for_each             = local.model_arns
  name                 = "${substr(var.cluster_name, 0, 25)}-model-${each.key}"
  permissions_boundary = var.permissions_boundary_arn
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.broker.arn }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy" "broker" {
  name = "exact-invocation-roles"
  role = aws_iam_role.broker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sts:AssumeRole"]
      Resource = [for role in aws_iam_role.invocation : role.arn]
    }]
  })
}

resource "aws_iam_role_policy" "invocation" {
  for_each = local.model_arns
  name     = "exact-regional-model"
  role     = aws_iam_role.invocation[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:CountTokens"]
      Resource = [each.value]
    }]
  })
}
