terraform {
  backend "s3" {
    bucket         = "shifter-infra-6b0a7ffb-5a68-471c-8280-c4882ce371d0"
    key            = "shifter/prod/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-6b0a7ffb-5a68-471c-8280-c4882ce371d0"
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
