module "portal_ecr" {
  source = "../../modules/ecr"

  repository_name      = var.portal_repository_name
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  tags = {
    Component = "portal"
  }
}

# ------------------------------------------------------------------------------
# Pulumi Provisioner ECR Repository
# ------------------------------------------------------------------------------

module "pulumi_provisioner_ecr" {
  source = "../../modules/ecr"

  repository_name      = var.pulumi_provisioner_repository_name
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })

  tags = {
    Component = "pulumi-provisioner"
  }
}

# ------------------------------------------------------------------------------
# S3 Cost Budget Alert
# Defense-in-depth monitoring for unusual S3 costs (e.g., billing attacks)
# ------------------------------------------------------------------------------

resource "aws_budgets_budget" "s3_cost_alert" {
  name         = "shifter-dev-s3-cost-alert"
  budget_type  = "COST"
  limit_amount = "50"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "Service"
    values = ["Amazon Simple Storage Service"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["YOUR_EMAIL@example.com"] # TODO: Replace with your email for budget alerts
  }
}
