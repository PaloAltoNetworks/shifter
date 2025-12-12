terraform {
  backend "s3" {
    bucket         = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key            = "dev/range/terraform.tfstate"
    region         = "us-east-2"
    dynamodb_table = "shifter-dev-terraform-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    encrypt        = true
  }
}

