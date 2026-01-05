terraform {
  backend "s3" {
    bucket         = "shifter-infra-6b0a7ffb-5a68-471c-8280-c4882ce371d0"
    key            = "prod/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-6b0a7ffb-5a68-471c-8280-c4882ce371d0"
    encrypt        = true
  }
}
