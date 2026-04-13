output "subnet_id" {
  value = aws_subnet.polaris.id
}

output "subnet_cidr" {
  value = aws_subnet.polaris.cidr_block
}

output "instance_id" {
  value = aws_instance.polaris.id
}

output "instance_private_ip" {
  value = aws_instance.polaris.private_ip
}

output "security_group_id" {
  value = aws_security_group.polaris.id
}

output "route_table_id" {
  value = aws_route_table.polaris.id
}

output "ssm_session_command" {
  value = "aws --profile panw-shifter-dev-workstation --region us-east-2 ssm start-session --target ${aws_instance.polaris.id}"
}

output "a2_dc_instance_id" {
  value = aws_instance.a2_dc.id
}

output "a2_dc_private_ip" {
  value = aws_instance.a2_dc.private_ip
}

output "a2_dc_ssm_session_command" {
  value = "aws --profile panw-shifter-dev-workstation --region us-east-2 ssm start-session --target ${aws_instance.a2_dc.id}"
}
