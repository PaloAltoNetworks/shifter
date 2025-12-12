terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.environment}-range"
}

# ------------------------------------------------------------------------------
# Range VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/range/vpc"

  name_prefix = local.name_prefix
  vpc_cidr    = var.vpc_cidr
  tags        = var.tags
}

