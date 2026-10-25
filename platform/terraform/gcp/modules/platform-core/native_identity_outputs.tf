output "native_identity" {
  description = "Public native database identity metadata; no tokens, passwords or policy credentials."
  value = {
    enabled                  = var.cloud_sql_iam_auth
    openfga_enabled          = var.openfga_enabled
    instance_connection_name = var.cloud_sql_iam_auth ? module.portal_cloud_sql.control_plane_database.instance_connection_name : ""
    database_users           = module.portal_iam.native_database_users
  }
}
