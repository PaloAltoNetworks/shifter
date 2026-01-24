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
      uuid               = local.instance_map[key].instance_uuid
      role               = local.instance_map[key].role
      os                 = local.instance_map[key].os_type
      subnet_name        = local.instance_map[key].subnet_name
      instance_id        = inst.id
      private_ip         = inst.private_ip
      ssh_key_secret_arn = aws_secretsmanager_secret.ssh_key[key].arn
      hostname           = "shifter-${local.instance_map[key].role}-${var.range_id}"
      ssh_public_key     = tls_private_key.instance[key].public_key_openssh
      xdr_agent_url      = local.instance_map[key].agent_url
      join_domain        = local.instance_map[key].join_domain
    }
  ]
}

output "dc_config_param_name" {
  description = "SSM parameter path for DC config (null if no DC)"
  value       = length(local.dc_instances) > 0 ? aws_ssm_parameter.dc_config[0].name : null
}
