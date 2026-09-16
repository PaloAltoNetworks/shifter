output "workload_identity_provider" {
  description = "Deployment's GitHub OIDC provider resource name (GCP_WORKLOAD_IDENTITY_PROVIDER)."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "packer_build_service_account_email" {
  description = "Packer build identity (GCP_PACKER_BUILD_SERVICE_ACCOUNT); federated only for enabled build contexts."
  value       = google_service_account.packer_build.email
}

output "packer_validate_service_account_email" {
  description = "Packer validation identity (GCP_PACKER_VALIDATE_SERVICE_ACCOUNT); null when validation is disabled."
  value       = try(google_service_account.validate[0].email, null)
}

output "packer_promote_service_account_email" {
  description = "Packer promotion identity (GCP_PACKER_PROMOTE_SERVICE_ACCOUNT); null when promotion is disabled."
  value       = try(google_service_account.promote[0].email, null)
}

output "deploy_service_account_email" {
  description = "Platform deploy identity (GCP_DEPLOY_SERVICE_ACCOUNT); null when this purpose is disabled."
  value       = try(google_service_account.deploy[0].email, null)
}

output "release_scan_service_account_email" {
  description = "Exact-release scanner identity (GCP_RELEASE_SCAN_SERVICE_ACCOUNT); null when this purpose is disabled."
  value       = try(google_service_account.release_scan[0].email, null)
}

output "release_evidence_bucket_name" {
  description = "Private access-controlled GCS bucket for raw validation, scan, and deployment evidence."
  value       = google_storage_bucket.release_evidence.name
}

output "destroy_service_account_email" {
  description = "Platform destroy identity (GCP_DESTROY_SERVICE_ACCOUNT); null when this purpose is disabled."
  value       = try(google_service_account.destroy[0].email, null)
}
