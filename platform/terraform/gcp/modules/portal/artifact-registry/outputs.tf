output "artifact_registry_repositories" {
  description = "Artifact Registry repositories by logical image role."
  value = {
    for name, repo in google_artifact_registry_repository.docker :
    name => repo.repository_id
  }
}

output "artifact_registry_image_roots" {
  description = "Artifact Registry image roots keyed by logical image role."
  value = {
    for name, repo in google_artifact_registry_repository.docker :
    name => "${var.artifact_registry_location}-docker.pkg.dev/${var.project_id}/${repo.repository_id}/${name}"
  }
}
