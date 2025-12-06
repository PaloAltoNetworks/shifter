terraform {
  backend "s3" {
    bucket         = "shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704"
    key            = "shifter/prod/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-29548208-505d-49da-87be-1c937681d079"
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
