terraform {
  backend "s3" {
    bucket         = "shifter-infra-514fdad5-dc1c-4aa4-acdc-ab44ff814936"
    key            = "prod/range/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-514fdad5-dc1c-4aa4-acdc-ab44ff814936"
    encrypt        = true
  }
}
