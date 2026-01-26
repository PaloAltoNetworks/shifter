# SSM Module Outputs

output "parameter_store_prefix" {
  description = "Parameter Store path prefix for portal configuration"
  value       = local.ps_prefix
}

output "image_tag_parameter_name" {
  description = "Parameter Store name for image tag (updated by CI/CD)"
  value       = aws_ssm_parameter.image_tag.name
}
