module "portal_ecr" {
  source = "../../modules/ecr"

  repository_name      = var.portal_repository_name
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  tags = {
    Component = "portal"
  }
}

module "mcp_shifter_ecr" {
  source = "../../modules/ecr"

  repository_name      = var.mcp_shifter_repository_name
  image_tag_mutability = "MUTABLE"
  scan_on_push         = true

  tags = {
    Component = "mcp-shifter"
  }
}
