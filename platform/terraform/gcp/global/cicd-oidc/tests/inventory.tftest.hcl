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

run "unseen_deployment" {
  command = plan

  assert {
    condition     = output.packer_validate_service_account_email == null && output.packer_promote_service_account_email == null
    error_message = "Deploy onboarding must not enable image purposes."
  }
}

run "overlapping_purpose_subjects" {
  command = plan
  variables {
    purpose_contexts = {
      deploy = [{
        environment           = "shared"
        ref                   = "refs/heads/main"
        workflow_ref          = "example/product/.github/workflows/deploy.yml@refs/heads/main"
        reusable_workflow_ref = ""
      }]
      destroy = [{
        environment           = "shared"
        ref                   = "refs/heads/main"
        workflow_ref          = "example/product/.github/workflows/gcp-dev-destroy.yml@refs/heads/main"
        reusable_workflow_ref = ""
      }]
    }
  }
  expect_failures = [var.purpose_contexts]
}

run "all_purposes_first_plan" {
  command = plan
  variables {
    purpose_contexts = {
      for purpose, workflow in {
        build        = "packer-gcp.yml", validate = "packer-gcp-validate.yml", promote = "packer-gcp-promote.yml",
        release_scan = "packer-gcp-release-scan.yml", deploy = "deploy.yml", destroy = "destroy.yml"
        } : purpose => [{
          environment           = "customer-${replace(purpose, "_", "-")}"
          ref                   = "refs/heads/main"
          workflow_ref          = "example/product/.github/workflows/${workflow}@refs/heads/main"
          reusable_workflow_ref = ""
      }]
    }
  }
}

run "case_insensitive_environment_ownership" {
  command = plan
  variables {
    purpose_contexts = {
      deploy = [{
        environment           = "Shared"
        ref                   = "refs/heads/main"
        workflow_ref          = "example/product/.github/workflows/deploy.yml@refs/heads/main"
        reusable_workflow_ref = ""
      }]
      destroy = [{
        environment           = "shared"
        ref                   = "refs/heads/main"
        workflow_ref          = "example/product/.github/workflows/destroy.yml@refs/heads/main"
        reusable_workflow_ref = ""
      }]
    }
  }
  expect_failures = [var.purpose_contexts]
}

# gcp-dev-destroy.yml rejects every dispatch ref except protected dev/main before
# auth, so a destroy tuple on the tenant deploy branch can never be satisfied.
run "destroy_on_protected_dev_with_tenant_deploy_branch" {
  command = plan
  variables {
    purpose_contexts = {
      deploy = [{
        environment           = "customer"
        ref                   = "refs/heads/customer"
        workflow_ref          = "example/product/.github/workflows/deploy.yml@refs/heads/customer"
        reusable_workflow_ref = ""
      }]
      destroy = [{
        environment           = "customer-destroy"
        ref                   = "refs/heads/dev"
        workflow_ref          = "example/product/.github/workflows/gcp-dev-destroy.yml@refs/heads/dev"
        reusable_workflow_ref = ""
      }]
    }
  }
}

run "destroy_on_tenant_branch" {
  command = plan
  variables {
    purpose_contexts = {
      deploy = [{
        environment           = "customer"
        ref                   = "refs/heads/customer"
        workflow_ref          = "example/product/.github/workflows/deploy.yml@refs/heads/customer"
        reusable_workflow_ref = ""
      }]
      destroy = [{
        environment           = "customer-destroy"
        ref                   = "refs/heads/customer"
        workflow_ref          = "example/product/.github/workflows/gcp-dev-destroy.yml@refs/heads/customer"
        reusable_workflow_ref = ""
      }]
    }
  }
  expect_failures = [var.purpose_contexts]
}
