output "packer_builder_subnetwork" {
  description = "Name of the packer builder subnet (set as the GCP_PACKER_SUBNETWORK GitHub variable)."
  value       = google_compute_subnetwork.packer_builder.name
}

output "gdc_vm_image_bucket" {
  description = "GCS bucket the built GCE images are exported into for the GDC VM Runtime."
  value       = google_storage_bucket.gdc_vm_images.name
}

# GCE-neutral name for the same staging bucket. The reusable GCE base-image
# publish path (packer-gcp.yml publish_target=ghcr, issue #2309) exports the
# built image here as a disk.raw tarball before pushing it to GHCR. Set this as
# the GCP_GCE_BASE_IMAGE_BUCKET GitHub variable. The GDC-named alias and the
# underlying bucket resource are retired with the rest of GDC in #2311.
output "gce_base_image_bucket" {
  description = "GCS staging bucket for reusable GCE base-image tarball exports (GCP_GCE_BASE_IMAGE_BUCKET)."
  value       = google_storage_bucket.gdc_vm_images.name
}
