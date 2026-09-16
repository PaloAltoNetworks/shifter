output "packer_builder_subnetwork" {
  description = "Name of the packer builder subnet (set as the GCP_PACKER_SUBNETWORK GitHub variable)."
  value       = google_compute_subnetwork.packer_builder.name
}

output "gdc_vm_image_bucket" {
  description = "GCS bucket the built GCE images are exported into for the GDC VM Runtime."
  value       = google_storage_bucket.gdc_vm_images.name
}
