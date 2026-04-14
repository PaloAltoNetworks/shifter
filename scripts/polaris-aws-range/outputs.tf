#------------------------------------------------------------------------------
# Outputs are keyed by range index so a consumer (bootstrap script, test
# harness, docs) can look up "range 2's polaris instance id" with a single
# terraform output lookup. For single-range deployments the maps still
# work — they just have one entry keyed "0".
#------------------------------------------------------------------------------

output "range_indices" {
  description = "Range index keys provisioned by this apply."
  value       = var.range_indices
}

output "range_subnet_ids" {
  description = "subnet id per range index."
  value       = { for k, s in aws_subnet.polaris : k => s.id }
}

output "range_subnet_cidrs" {
  description = "/28 CIDR per range index."
  value       = { for k, s in aws_subnet.polaris : k => s.cidr_block }
}

output "range_polaris_instance_ids" {
  description = "polaris VM EC2 instance id per range index."
  value       = { for k, i in aws_instance.polaris : k => i.id }
}

output "range_polaris_private_ips" {
  description = "polaris VM private IP per range index (pinned to .10 of the subnet)."
  value       = { for k, i in aws_instance.polaris : k => i.private_ip }
}

output "range_a2_instance_ids" {
  description = "A2 Windows DC EC2 instance id per range index."
  value       = { for k, i in aws_instance.a2_dc : k => i.id }
}

output "range_a2_private_ips" {
  description = "A2 Windows DC private IP per range index (pinned to .11 of the subnet)."
  value       = { for k, i in aws_instance.a2_dc : k => i.private_ip }
}

output "range_security_group_ids" {
  description = "Per-range security group id (scoped to each range's /28)."
  value       = { for k, sg in aws_security_group.polaris : k => sg.id }
}

output "iam_instance_profile_name" {
  description = "Shared instance profile attached to every polaris + A2 instance."
  value       = aws_iam_instance_profile.polaris.name
}

output "ssm_session_commands" {
  description = "aws ssm start-session commands per range, pre-formatted for copy-paste."
  value = {
    for k in var.range_indices : k => {
      polaris = "aws --profile panw-shifter-dev-workstation --region us-east-2 ssm start-session --target ${aws_instance.polaris[k].id}"
      a2_dc   = "aws --profile panw-shifter-dev-workstation --region us-east-2 ssm start-session --target ${aws_instance.a2_dc[k].id}"
    }
  }
}
