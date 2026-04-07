# KubeVirt module outputs

output "artifact_registry_repository" {
  description = "Full Artifact Registry repository path for containerDisk images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.vm_images.repository_id}"
}

output "artifact_registry_id" {
  description = "Artifact Registry repository ID"
  value       = google_artifact_registry_repository.vm_images.repository_id
}

output "kubevirt_version" {
  description = "Installed KubeVirt version"
  value       = var.kubevirt_version
}

output "cdi_version" {
  description = "Installed CDI version"
  value       = var.cdi_version
}
