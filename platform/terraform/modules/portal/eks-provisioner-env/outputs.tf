output "runtime_env" {
  description = "Management-plane runtime_env merged with the assembled provisioner Job environment, for the chart render."
  value       = local.merged_runtime_env
  sensitive   = true
}

output "provisioner_env_keys" {
  description = "Sorted names of the assembled provisioner env keys (diagnostic; the contract parity is enforced in the platform test suite)."
  value       = sort(keys(local.provisioner_env))
}
