output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_spot_instance_request.runner.spot_instance_id
}

output "ssm_command" {
  description = "SSM command to connect"
  value       = "aws ssm start-session --target ${aws_spot_instance_request.runner.spot_instance_id} --region ${var.region}"
}

output "registration_instructions" {
  description = "Steps to register the runner with GitHub"
  value       = <<-EOT

    1. Go to: https://github.com/${var.github_org}/${var.github_repo}/settings/actions/runners/new
    2. Copy the token from the "Configure" section
    3. Connect via SSM:
       aws ssm start-session --target ${aws_spot_instance_request.runner.spot_instance_id} --region ${var.region}
    4. Run:
       cd /home/ec2-user/actions-runner
       sudo -u ec2-user ./config.sh --url https://github.com/${var.github_org}/${var.github_repo} --token YOUR_TOKEN
       sudo ./svc.sh install
       sudo ./svc.sh start
    5. Update your workflows to use: runs-on: self-hosted

  EOT
}
