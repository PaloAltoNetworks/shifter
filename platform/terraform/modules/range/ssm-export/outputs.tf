output "parameter_prefix" {
  description = "SSM Parameter Store path prefix under which the range contract is published."
  value       = local.ps_prefix
}

output "published_parameter_names" {
  description = "Fully-qualified names of the SSM parameters published (empty values are skipped)."
  value       = sort([for p in aws_ssm_parameter.range : p.name])
}
