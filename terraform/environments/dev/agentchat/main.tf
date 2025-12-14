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
  name_prefix = "${var.environment}-agentchat"
}

# ------------------------------------------------------------------------------
# Remote State - Portal VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "portal" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "dev/portal/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

module "ec2" {
  source = "../../../modules/agentchat/ec2"

  aws_region       = var.aws_region
  name_prefix      = local.name_prefix
  vpc_id           = data.terraform_remote_state.portal.outputs.vpc_id
  subnet_id        = data.terraform_remote_state.portal.outputs.private_subnet_ids[0]
  instance_type    = var.ec2_instance_type
  root_volume_size = var.ec2_root_volume_size

  # OpenWebUI PostgreSQL credentials (from Portal RDS)
  openwebui_db_secret_arn = data.terraform_remote_state.portal.outputs.openwebui_db_secret_arn

  tags = var.tags
}
