terraform {
  backend "s3" {
    bucket         = "shifter-infra-b4cc1e89-0c58-452e-ae30-0e932b4e27a0"
    key            = "prod/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-b4cc1e89-0c58-452e-ae30-0e932b4e27a0"
    encrypt        = true
  }
}
