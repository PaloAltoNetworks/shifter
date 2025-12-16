module "portal_ecr" {
  source = "../../modules/ecr"

  repository_name      = var.portal_repository_name
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  tags = {
    Component = "portal"
  }
}
