terraform {
  backend "s3" {
    bucket         = "shifter-infra-b4cc1e89-0c58-452e-ae30-0e932b4e27a0"
    key            = "shifter/prod/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-b4cc1e89-0c58-452e-ae30-0e932b4e27a0"
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
      Environment = "prod"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }
  }
}
