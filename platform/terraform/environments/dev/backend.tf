terraform {
  backend "s3" {
    bucket         = "shifter-dev-infra-b7113d6f-5aec-4531-ad09-2e62b51c2a86"
    key            = "shifter/dev/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-dev-terraform-b7113d6f-5aec-4531-ad09-2e62b51c2a86"
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
