# GCP IAM module outputs
#
# After applying, add these as GitHub secrets:
#   GCP_WORKLOAD_IDENTITY_PROVIDER = workload_identity_provider
#   GCP_SERVICE_ACCOUNT            = service_account_email
#   GCP_PROJECT_ID                 = project_id

output "workload_identity_provider" {
  description = "Full resource name of the WIF provider (for GitHub Actions google-github-actions/auth)"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "workload_identity_pool_id" {
  description = "Workload Identity Pool ID"
  value       = google_iam_workload_identity_pool.github.workload_identity_pool_id
}

output "service_account_email" {
  description = "CI/CD service account email (for GitHub Actions)"
  value       = google_service_account.github_actions.email
}

output "project_id" {
  description = "GCP project ID"
  value       = var.project_id
}

output "terraform_state_bucket" {
  description = "GCS bucket name for Terraform state"
  value       = google_storage_bucket.terraform_state.name
}
