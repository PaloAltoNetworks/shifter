terraform {
  backend "s3" {
    bucket         = "shifter-infra-95c922ca-35ca-4787-9fc6-626a2b04f142"
    key            = "shifter/prod/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-terraform-95c922ca-35ca-4787-9fc6-626a2b04f142"
    encrypt        = true
  }
}
