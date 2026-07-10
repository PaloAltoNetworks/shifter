# State migration for platform-core module decomposition (issue #504).
# Preserves existing gcp-dev (and future) state addresses when resources
# moved from the monolithic module into provider-native submodules.

moved {
  from = google_project_service.required
  to   = module.project_services.google_project_service.required
}

moved {
  from = google_compute_network.platform
  to   = module.portal_vpc.google_compute_network.platform
}

moved {
  from = google_compute_network.range
  to   = module.range_vpc.google_compute_network.range
}

moved {
  from = google_compute_subnetwork.gke
  to   = module.portal_vpc.google_compute_subnetwork.gke
}

moved {
  from = google_compute_router.nat
  to   = module.portal_vpc.google_compute_router.nat
}

moved {
  from = google_compute_address.nat
  to   = module.portal_vpc.google_compute_address.nat
}

moved {
  from = google_compute_router_nat.nat
  to   = module.portal_vpc.google_compute_router_nat.nat
}

moved {
  from = google_compute_router.range_nat
  to   = module.range_vpc.google_compute_router.range_nat
}

moved {
  from = google_compute_address.range_nat
  to   = module.range_vpc.google_compute_address.range_nat
}

moved {
  from = google_compute_router_nat.range_nat
  to   = module.range_vpc.google_compute_router_nat.range_nat
}

moved {
  from = google_compute_firewall.range_deny_ingress_all
  to   = module.range_vpc.google_compute_firewall.range_deny_ingress_all
}

moved {
  from = google_compute_firewall.range_allow_platform_provisioner
  to   = module.range_vpc.google_compute_firewall.range_allow_platform_provisioner
}

moved {
  from = google_compute_firewall.range_allow_operator_admin_ssh[0]
  to   = module.range_vpc.google_compute_firewall.range_allow_operator_admin_ssh[0]
}

moved {
  from = terraform_data.range_egress_invariant
  to   = module.range_vpc.terraform_data.range_egress_invariant
}

moved {
  from = google_compute_firewall.range_egress_deny_all[0]
  to   = module.range_vpc.google_compute_firewall.range_egress_deny_all[0]
}

moved {
  from = google_compute_firewall.range_egress_allow_allowlist[0]
  to   = module.range_vpc.google_compute_firewall.range_egress_allow_allowlist[0]
}

moved {
  from = google_compute_firewall.platform_deny_external_ssh_rdp
  to   = module.portal_vpc.google_compute_firewall.platform_deny_external_ssh_rdp
}

moved {
  from = google_compute_firewall.platform_allow_gke_health_checks
  to   = module.portal_vpc.google_compute_firewall.platform_allow_gke_health_checks
}

moved {
  from = google_compute_firewall.platform_allow_operator_admin_ssh[0]
  to   = module.portal_vpc.google_compute_firewall.platform_allow_operator_admin_ssh[0]
}

moved {
  from = google_compute_global_address.services
  to   = module.portal_vpc.google_compute_global_address.services
}

moved {
  from = google_service_networking_connection.services
  to   = module.portal_vpc.google_service_networking_connection.services
}

moved {
  from = google_service_account.gke_nodes
  to   = module.portal_iam.google_service_account.gke_nodes
}

moved {
  from = google_service_account.workload
  to   = module.portal_iam.google_service_account.workload
}

moved {
  from = google_kms_key_ring.artifact_registry
  to   = module.portal_artifact_registry.google_kms_key_ring.artifact_registry
}

moved {
  from = google_kms_crypto_key.artifact_registry
  to   = module.portal_artifact_registry.google_kms_crypto_key.artifact_registry
}

moved {
  from = google_kms_crypto_key_iam_member.artifact_registry
  to   = module.portal_artifact_registry.google_kms_crypto_key_iam_member.artifact_registry
}

moved {
  from = google_artifact_registry_repository.docker
  to   = module.portal_artifact_registry.google_artifact_registry_repository.docker
}

moved {
  from = google_storage_bucket.assets
  to   = module.portal_gcs.google_storage_bucket.assets
}

moved {
  from = google_storage_bucket.audit_logs
  to   = module.portal_gcs.google_storage_bucket.audit_logs
}

moved {
  from = google_storage_bucket_object.identity_platform_before_create
  to   = module.portal_identity_platform.google_storage_bucket_object.identity_platform_before_create
}

moved {
  from = google_cloudfunctions_function.identity_platform_before_create
  to   = module.portal_identity_platform.google_cloudfunctions_function.identity_platform_before_create
}

moved {
  from = google_cloudfunctions_function_iam_member.identity_platform_before_create_invoker
  to   = module.portal_identity_platform.google_cloudfunctions_function_iam_member.identity_platform_before_create_invoker
}

moved {
  from = google_compute_global_address.platform_ingress
  to   = module.portal_ingress.google_compute_global_address.platform_ingress
}

moved {
  from = google_compute_security_policy.platform_edge
  to   = module.portal_ingress.google_compute_security_policy.platform_edge
}

moved {
  from = google_dns_managed_zone.platform[0]
  to   = module.portal_ingress.google_dns_managed_zone.platform[0]
}

moved {
  from = google_dns_record_set.platform_ingress[0]
  to   = module.portal_ingress.google_dns_record_set.platform_ingress[0]
}

moved {
  from = google_pubsub_topic.platform_events
  to   = module.portal_messaging.google_pubsub_topic.platform_events
}

moved {
  from = google_pubsub_subscription.platform_events
  to   = module.portal_messaging.google_pubsub_subscription.platform_events
}

moved {
  from = google_identity_platform_config.platform
  to   = module.portal_identity_platform.google_identity_platform_config.platform
}

moved {
  from = google_secret_manager_secret.runtime
  to   = module.portal_secrets.google_secret_manager_secret.runtime
}

moved {
  from = random_password.db_password
  to   = module.portal_cloud_sql.random_password.db_password
}

moved {
  from = random_password.django_secret_key
  to   = module.portal_secrets.random_password.django_secret_key
}

moved {
  from = random_id.field_encryption_key
  to   = module.portal_secrets.random_id.field_encryption_key
}

moved {
  from = random_password.guacamole_db_password
  to   = module.portal_cloud_sql.random_password.guacamole_db_password
}

moved {
  from = random_id.guacamole_json_auth_secret
  to   = module.portal_secrets.random_id.guacamole_json_auth_secret
}

moved {
  from = google_sql_database_instance.platform
  to   = module.portal_cloud_sql.google_sql_database_instance.platform
}

moved {
  from = google_sql_database.platform
  to   = module.portal_cloud_sql.google_sql_database.platform
}

moved {
  from = google_sql_database.guacamole
  to   = module.portal_cloud_sql.google_sql_database.guacamole
}

moved {
  from = google_sql_user.platform
  to   = module.portal_cloud_sql.google_sql_user.platform
}

moved {
  from = google_sql_user.guacamole
  to   = module.portal_cloud_sql.google_sql_user.guacamole
}

moved {
  from = google_redis_instance.platform
  to   = module.portal_redis.google_redis_instance.platform
}

moved {
  from = google_secret_manager_secret_version.runtime_seeded
  to   = module.portal_secrets.google_secret_manager_secret_version.runtime_seeded
}

moved {
  from = google_container_cluster.platform
  to   = module.portal_gke.google_container_cluster.platform
}

moved {
  from = google_container_node_pool.web
  to   = module.portal_gke.google_container_node_pool.web
}

moved {
  from = google_project_iam_member.node_roles
  to   = module.portal_iam.google_project_iam_member.node_roles
}

moved {
  from = google_project_iam_member.workload_roles
  to   = module.portal_iam.google_project_iam_member.workload_roles
}

moved {
  from = google_service_account_iam_member.workload_identity
  to   = module.portal_iam.google_service_account_iam_member.workload_identity
}

moved {
  from = google_container_node_pool.workers
  to   = module.portal_gke.google_container_node_pool.workers
}

moved {
  from = google_container_node_pool.provisioner
  to   = module.portal_gke.google_container_node_pool.provisioner
}
