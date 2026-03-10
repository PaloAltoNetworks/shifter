terraform {
  backend "s3" {
    bucket         = "shifter-dev-infra-2080ea59-c141-4021-9ddd-11c77cd0574d"
    key            = "shifter/dev/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-dev-terraform-2080ea59-c141-4021-9ddd-11c77cd0574d"
    encrypt        = true
  }

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

  default_tags {
    tags = {
      Environment = "dev"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }
  }
}
