# Guacamole data-plane credentials (AWS EKS parity with the GCP cloud-sql +
# secrets modules, ADR-044-R6). RDS exposes no native Terraform user/database
# resource and the deploy runner has no network path to the portal RDS, so the
# guacamole_admin role and its database are created in-cluster by
# scripts/bootstrap/aws_eks.py (provision_guacamole_database) using the
# credentials generated here. The values live in the eks-owned Secrets Manager
# containers "guacamole-db" and "guacamole-json-auth" (created by the
# var.secret_names loop in kms_secrets.tf and surfaced through the secret_arns
# output), and are synced into the guacamole-runtime Kubernetes Secret before the
# Helm install. The JSON-auth key is the shared signing secret: the portal reads
# it as GUACAMOLE_JSON_AUTH_SECRET and guacamole-client as JSON_SECRET_KEY.

resource "random_password" "guacamole_db" {
  length  = 32
  special = true
  # Keep to specials that are safe as a psycopg literal and a PGPASSWORD env
  # value; excludes quotes/backslash/slash that complicate SQL/URL contexts.
  override_special = "!#%*()-_=+?"
}

resource "random_id" "guacamole_json_auth" {
  byte_length = 32
}

resource "aws_secretsmanager_secret_version" "guacamole_db" {
  secret_id = aws_secretsmanager_secret.platform["guacamole-db"].id
  secret_string = jsonencode({
    username = "guacamole_admin"
    password = random_password.guacamole_db.result
    dbname   = "guacamole"
  })
}

resource "aws_secretsmanager_secret_version" "guacamole_json_auth" {
  secret_id     = aws_secretsmanager_secret.platform["guacamole-json-auth"].id
  secret_string = random_id.guacamole_json_auth.hex
}
