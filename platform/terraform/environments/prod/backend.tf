terraform {
  backend "s3" {
    bucket         = "shifter-infra-c0045c36-4e43-4710-9a2e-ce8534cb5851"
    key            = "shifter/prod/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-c0045c36-4e43-4710-9a2e-ce8534cb5851"
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
