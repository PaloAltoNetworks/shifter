output "listener_security_group_id" {
  description = "Exact NLB source security group for target pod ingress."
  value       = aws_security_group.listener.id
}
output "deployment" {
  description = "Non-secret applied broker transport, identities and endpoint addresses."
  value = merge(var.settings, {
    role_arn             = aws_iam_role.broker.arn
    provisioner_subject  = var.provisioner_subject
    region               = var.region
    invocation_roles     = { for name, role in aws_iam_role.invocation : name => role.arn }
    target_group_arn     = aws_lb_target_group.broker.arn
    vpc_id               = var.vpc_id
    endpoint_cidrs       = sort([for nic in data.aws_network_interface.endpoint : "${nic.private_ip}/32"])
    guest_endpoint_cidrs = sort([for nic in data.aws_network_interface.listener : "${nic.private_ip}/32"])
    health_check_cidrs   = sort([for subnet in var.private_subnets : subnet.cidr])
  })
}
