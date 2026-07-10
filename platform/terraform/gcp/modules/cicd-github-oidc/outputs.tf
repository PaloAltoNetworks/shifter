output "workload_identity_provider" {
  description = "Full resource name of the GitHub OIDC provider (set as the GCP_WORKLOAD_IDENTITY_PROVIDER GitHub secret)."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "packer_build_service_account_email" {
  description = "Email of the packer build service account (set as the GCP_SERVICE_ACCOUNT GitHub secret)."
  value       = google_service_account.packer_build.email
}

output "packer_builder_subnetwork" {
  description = "Name of the packer builder subnet (set as the GCP_PACKER_SUBNETWORK GitHub variable)."
  value       = google_compute_subnetwork.packer_builder.name
}

output "gdc_vm_image_bucket" {
  description = "GCS bucket the built GCE images are exported into for the GDC VM Runtime."
  value       = google_storage_bucket.gdc_vm_images.name
}
