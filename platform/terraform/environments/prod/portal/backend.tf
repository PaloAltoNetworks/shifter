terraform {
  backend "s3" {
    bucket         = "shifter-infra-70b88946-f5a5-45df-9d33-e8c2257158fd"
    key            = "prod/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-70b88946-f5a5-45df-9d33-e8c2257158fd"
    encrypt        = true
  }
}
