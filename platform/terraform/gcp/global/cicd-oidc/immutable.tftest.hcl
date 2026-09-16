mock_provider "google" {}

variables {
  project_number               = "789"
  project_id                   = "example-project"
  environment                  = "unseen-customer"
  name_prefix                  = "cust-unseen"
  region                       = "us-central1"
  github_org                   = "example"
  github_repo                  = "product"
  github_repository_id         = "123"
  github_owner_id              = "456"
  release_evidence_bucket_name = "example-customer-evidence"
  terraform_state_bucket_name  = "example-platform-state"
  purpose_contexts = {
    deploy = [{
      environment           = "customer-deploy"
      ref                   = "refs/heads/main"
      workflow_ref          = "example/product/.github/workflows/deploy.yml@refs/heads/main"
      reusable_workflow_ref = ""
    }]
    destroy = [{
      environment           = "customer-destroy"
      ref                   = "refs/heads/main"
      workflow_ref          = "example/product/.github/workflows/gcp-dev-destroy.yml@refs/heads/main"
      reusable_workflow_ref = ""
    }]
  }
}

run "immutable_repository_subjects" {
  command = plan
  module {
    source = "../../modules/cicd-oidc-identity"
  }
  variables {
    github_subject_format = "immutable"
  }
  assert {
    condition     = strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, "assertion.sub == 'repo:example@456/product@123:environment:customer-deploy'")
    error_message = "Immutable trust must bind the reviewed owner and repository IDs."
  }
  assert {
    condition     = google_service_account_iam_member.deploy_wif["repo:example@456/product@123:environment:customer-deploy"].member == "principal://iam.googleapis.com/projects/789/locations/global/workloadIdentityPools/cust-unseen-github/subject/repo:example@456/product@123:environment:customer-deploy"
    error_message = "The deploy binding must use the same exact immutable subject."
  }
}
