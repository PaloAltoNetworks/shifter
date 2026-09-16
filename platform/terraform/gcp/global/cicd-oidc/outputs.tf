output "workload_identity_provider" {
  description = "GitHub OIDC provider resource name; set as the GCP_WORKLOAD_IDENTITY_PROVIDER GitHub secret."
  value       = module.cicd_oidc_identity.workload_identity_provider
}

output "packer_build_service_account_email" {
  description = "Packer build service account email; set as GCP_PACKER_BUILD_SERVICE_ACCOUNT."
  value       = module.cicd_oidc_identity.packer_build_service_account_email
}

output "packer_validate_service_account_email" {
  description = "Packer validate service account email; set as GCP_PACKER_VALIDATE_SERVICE_ACCOUNT."
  value       = module.cicd_oidc_identity.packer_validate_service_account_email
}

output "packer_promote_service_account_email" {
  description = "Packer promote service account email; set as GCP_PACKER_PROMOTE_SERVICE_ACCOUNT."
  value       = module.cicd_oidc_identity.packer_promote_service_account_email
}

output "deploy_service_account_email" {
  description = "Platform deploy service account email; set as GCP_DEPLOY_SERVICE_ACCOUNT."
  value       = module.cicd_oidc_identity.deploy_service_account_email
}

output "release_scan_service_account_email" {
  description = "Exact-release scanner service account email; set as GCP_RELEASE_SCAN_SERVICE_ACCOUNT."
  value       = module.cicd_oidc_identity.release_scan_service_account_email
}

output "release_evidence_bucket_name" {
  description = "Private GCS bucket that stores raw release evidence."
  value       = module.cicd_oidc_identity.release_evidence_bucket_name
}

output "destroy_service_account_email" {
  description = "Platform destroy service account email; set as GCP_DESTROY_SERVICE_ACCOUNT."
  value       = module.cicd_oidc_identity.destroy_service_account_email
}
