output "runner_instance_ids" {
  description = "Instance IDs of the GitHub Actions runners"
  value       = aws_spot_instance_request.runner[*].spot_instance_id
}

output "runner_names" {
  description = "Names of the GitHub Actions runners"
  value       = [for i in range(var.runner_count) : "shifter-github-runner-${i + 1}"]
}

output "ssm_commands" {
  description = "SSM commands to connect to each runner"
  value = [
    for id in aws_spot_instance_request.runner[*].spot_instance_id :
    "aws ssm start-session --target ${id} --region ${var.region}"
  ]
}
