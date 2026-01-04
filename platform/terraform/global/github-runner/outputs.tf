# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "webhook_endpoint" {
  description = "GitHub webhook URL - configure this in your GitHub App settings"
  value       = module.github_runner.webhook.endpoint
}

output "webhook_secret_ssm_path" {
  description = "SSM path where webhook secret is stored"
  value       = var.github_app_webhook_secret_ssm_path
}

output "runner_labels" {
  description = "Labels that runners will register with"
  value       = ["self-hosted", "linux", "x64", "shifter", var.environment]
}
