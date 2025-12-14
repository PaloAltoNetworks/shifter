terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.environment}-librechat"
}

# ------------------------------------------------------------------------------
# Remote State - Portal VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "portal" {
  backend = "s3"
  config = {
    bucket = "shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704"
    key    = "prod/portal/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# LibreChat Module
# ------------------------------------------------------------------------------

module "librechat" {
  source = "../../../modules/librechat"

  aws_region             = var.aws_region
  name_prefix            = local.name_prefix
  vpc_id                 = data.terraform_remote_state.portal.outputs.vpc_id
  private_route_table_id = data.terraform_remote_state.portal.outputs.private_route_table_id
  availability_zone      = data.terraform_remote_state.portal.outputs.availability_zones[0]
  subnet_cidr            = var.subnet_cidr

  instance_type      = var.instance_type
  root_volume_size   = var.root_volume_size
  data_volume_size   = var.data_volume_size
  app_title          = var.app_title
  allow_registration = var.allow_registration

  tags = var.tags
}
