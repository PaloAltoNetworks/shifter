terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend configured via -backend-config during init
  # This allows separate state per environment
  # checkov:skip=CKV_TF_3: State locking is configured via DynamoDB in external backend config files (dev.s3.tfbackend, prod.s3.tfbackend). The dynamodb_table parameter is provided via -backend-config during terraform init.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "shifter"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}
