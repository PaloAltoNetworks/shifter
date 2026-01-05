terraform {
  backend "s3" {
    bucket         = "shifter-infra-9fad3e21-51a9-4e09-ae3c-497b31211f6c"
    key            = "prod/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-9fad3e21-51a9-4e09-ae3c-497b31211f6c"
    encrypt        = true
  }
}
