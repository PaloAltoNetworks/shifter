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
