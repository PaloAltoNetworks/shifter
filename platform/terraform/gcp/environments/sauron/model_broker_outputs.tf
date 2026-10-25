output "model_broker" {
  description = "Deployment-owned broker transport, references and identity inventory."
  value       = module.platform_core.model_broker
}
