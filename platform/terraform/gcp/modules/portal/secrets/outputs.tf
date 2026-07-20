output "runtime_secret_ids" {
  description = "Secret Manager secret resource IDs for runtime secret bundles."
  value = {
    for name, secret in google_secret_manager_secret.runtime :
    name => secret.id
  }
}
