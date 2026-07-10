output "runner_instance_ids" {
  description = "Instance IDs of the GitHub Actions runners"
  value       = aws_instance.runner[*].id
}

output "runner_names" {
  description = "Names of the GitHub Actions runners"
  value       = [for i in range(var.runner_count) : "shifter-github-runner-${i + 1}"]
}

output "ssm_commands" {
  description = "SSM commands to connect to each runner"
  value = [
    for id in aws_instance.runner[*].id :
    "aws ssm start-session --target ${id} --region ${var.region}"
  ]
}

output "runner_alerts_topic_arn" {
  description = "ARN of the SNS topic that receives runner-health alarm notifications. Subscribe email/Slack/Teams here."
  value       = aws_sns_topic.runner_alerts.arn
}
