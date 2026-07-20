output "subnets" {
  description = "Created subnets with IDs and CIDRs"
  value = {
    for name, subnet in aws_subnet.range : name => {
      uuid              = local.subnet_map[name].uuid
      subnet_id         = subnet.id
      subnet_cidr       = subnet.cidr_block
      security_group_id = aws_security_group.subnet[name].id
      route_table_id    = aws_route_table.subnet[name].id
    }
  }
}

output "instances" {
  description = "Created instances with IDs and IPs for Ansible runner"
  value = [
    for key, inst in aws_instance.range : {
      uuid                        = local.instance_map[key].instance_uuid
      name                        = local.instance_map[key].name
      role                        = local.instance_map[key].role
      os                          = local.instance_map[key].os_type
      subnet_name                 = local.instance_map[key].subnet_name
      instance_id                 = inst.id
      private_ip                  = inst.private_ip
      ssh_key_secret_arn          = aws_secretsmanager_secret.ssh_key[key].arn
      rdp_password_secret_arn     = aws_secretsmanager_secret.guest_password[key].arn
      rdp_password_ssm_param_name = aws_ssm_parameter.guest_password[key].name
      hostname                    = local.instance_map[key].name != "" ? local.instance_map[key].name : "shifter-${local.instance_map[key].role}-${var.range_id}"
      public_key                  = tls_private_key.instance[key].public_key_openssh
      xdr_agent_url               = local.instance_map[key].agent_url
      join_domain                 = local.instance_map[key].join_domain
    }
  ]
}

output "dc_config_param_name" {
  description = "SSM parameter path for DC config (null if no DC)"
  value       = length(local.dc_instances) > 0 ? aws_ssm_parameter.dc_config[0].name : null
}

output "polaris_agent_role_arn" {
  description = "ARN of the per-range Polaris Bedrock agent role (empty string when polaris_agent_enabled is false)"
  value       = try(aws_iam_role.polaris_agent[0].arn, "")
}

output "vpn_gateway" {
  description = "Non-secret OpenVPN infrastructure endpoint awaiting a service-level readiness probe"
  value = local.vpn_enabled ? {
    endpoint        = aws_lb.vpn[0].dns_name
    port            = 1194
    health_endpoint = aws_instance.vpn_gateway[0].private_ip
    health_port     = 1195
    target_ref      = local.instance_map[local.vpn_target_key].instance_uuid
    ready           = false
  } : null
}
