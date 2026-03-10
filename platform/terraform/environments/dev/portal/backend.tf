terraform {
  backend "s3" {
    bucket         = "shifter-dev-infra-2080ea59-c141-4021-9ddd-11c77cd0574d"
    key            = "dev/portal/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-dev-terraform-2080ea59-c141-4021-9ddd-11c77cd0574d"
    encrypt        = true
  }
}
