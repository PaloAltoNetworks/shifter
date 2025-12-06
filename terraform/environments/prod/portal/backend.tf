terraform {
  backend "s3" {
    bucket         = "shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704"
    key            = "prod/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-29548208-505d-49da-87be-1c937681d079"
    encrypt        = true
  }
}
