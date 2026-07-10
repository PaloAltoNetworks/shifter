resource "google_kms_key_ring" "artifact_registry" {
  name     = "${var.name_prefix}-ar"
  location = var.artifact_registry_location
  project  = var.project_id
}

resource "google_kms_crypto_key" "artifact_registry" {
  name            = "${var.name_prefix}-ar-docker"
  key_ring        = google_kms_key_ring.artifact_registry.id
  rotation_period = "7776000s"
  purpose         = "ENCRYPT_DECRYPT"
  labels          = var.common_labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "artifact_registry" {
  crypto_key_id = google_kms_crypto_key.artifact_registry.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${var.project_number}@gcp-sa-artifactregistry.iam.gserviceaccount.com"
}

resource "google_artifact_registry_repository" "docker" {
  for_each = var.artifact_repositories

  project       = var.project_id
  location      = var.artifact_registry_location
  repository_id = "${var.name_prefix}-${each.key}"
  description   = "Docker images for ${each.key} in ${var.environment}"
  format        = "DOCKER"
  kms_key_name  = google_kms_crypto_key.artifact_registry.id

  depends_on = [google_kms_crypto_key_iam_member.artifact_registry]
}
