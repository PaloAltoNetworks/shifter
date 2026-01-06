terraform {
  backend "s3" {
    bucket         = "shifter-infra-c0045c36-4e43-4710-9a2e-ce8534cb5851"
    key            = "prod/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-c0045c36-4e43-4710-9a2e-ce8534cb5851"
    encrypt        = true
  }
}
