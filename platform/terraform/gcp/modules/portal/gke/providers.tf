# Keep module contract tests on the same provider family as deployment roots.
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.1"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 8.1"
    }
  }
}
