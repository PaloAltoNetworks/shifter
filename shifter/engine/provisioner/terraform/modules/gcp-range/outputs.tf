output "subnets" {
  description = "Created subnetworks with IDs and CIDRs."
  value = {
    for name, subnet in google_compute_subnetwork.range : name => {
      uuid                     = local.subnet_map[name].uuid
      subnet_id                = subnet.self_link
      subnet_cidr              = subnet.ip_cidr_range
      security_group_id        = local.subnet_target_tags[name]
      route_table_id           = ""
      gcp_subnetwork_name      = subnet.name
      gcp_subnetwork_id        = subnet.id
      gcp_subnetwork_self_link = subnet.self_link
      gcp_target_tag           = local.subnet_target_tags[name]
    }
  }
}

output "instances" {
  description = "Created GCE instances with IDs and private IPs."
  value = [
    for key, inst in google_compute_instance.range : {
      uuid                   = local.instance_map[key].instance_uuid
      name                   = local.instance_map[key].display_name
      role                   = local.instance_map[key].role
      os                     = local.instance_map[key].os_type
      subnet_name            = local.instance_map[key].subnet_name
      instance_id            = inst.name
      private_ip             = inst.network_interface[0].network_ip
      ssh_key_secret_arn     = google_secret_manager_secret.ssh_key[key].id
      hostname               = local.instance_map[key].hostname
      public_key             = tls_private_key.instance[key].public_key_openssh
      xdr_agent_url          = local.instance_map[key].agent_url
      join_domain            = local.instance_map[key].join_domain
      gcp_instance_name      = inst.name
      gcp_instance_id        = inst.id
      gcp_instance_self_link = inst.self_link
      gcp_zone               = inst.zone
      gcp_subnetwork         = google_compute_subnetwork.range[local.instance_map[key].subnet_name].self_link
    }
  ]
}

output "dc_config_param_name" {
  description = "Secret Manager resource ID for DC config bootstrap data (null if no DC)."
  value       = length(local.dc_instances) > 0 ? google_secret_manager_secret.dc_config[0].id : null
}
