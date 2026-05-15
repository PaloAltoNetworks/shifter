# ------------------------------------------------------------------------------
# Secrets Manager — Domain Controller domain Administrator password
# ------------------------------------------------------------------------------
# Terraform-managed, same pattern as the portal RDS credentials
# (modules/portal/rds) and the Django-app secret (environments/*/portal):
# a random_password generated at apply time and stored in Secrets Manager.
# It is read at runtime as DC_DOMAIN_PASSWORD by the engine provisioner ECS
# task (via `secrets = [...]` in task_definition.tf) and by the portal Django
# container (via the portal/ssm + portal/ec2 modules and entrypoint.sh), and
# is the value the engine provisioner uses to promote each prebaked DC AMI
# (and to domain-join victims) — see shifter/engine/provisioner. The cleartext
# never appears in committed source; it lives only in Secrets Manager and in
# Terraform state (S3 backend, restricted), exactly like the DB and app
# credentials. Rotation:
#   terraform apply -replace='module.engine_provisioner.random_password.dc_domain_password'
# then re-promote affected DCs (or let the next range provision pick it up).

resource "random_password" "dc_domain_password" {
  length  = 24
  special = true
  # Restrict the symbol set to characters that survive PowerShell / shell
  # interpolation in the DC bootstrap path while still meeting Windows AD
  # complexity (length + the character classes guarantee upper/lower/digit/
  # symbol coverage in practice).
  override_special = "!@#%^&*()-_=+[]{}:?"
}

resource "aws_secretsmanager_secret" "dc_domain_password" {
  name                    = "shifter-${var.environment}-portal-dc-domain"
  description             = "Domain Controller domain Administrator password (DC_DOMAIN_PASSWORD)"
  recovery_window_in_days = 0 # NOSONAR - matches the other portal secrets: immediate deletion avoids naming conflicts on recreate
  kms_key_id              = var.secrets_manager_kms_key_arn

  tags = merge(local.common_tags, {
    Name = "shifter-${var.environment}-portal-dc-domain"
  })
}

resource "aws_secretsmanager_secret_version" "dc_domain_password" {
  secret_id     = aws_secretsmanager_secret.dc_domain_password.id
  secret_string = random_password.dc_domain_password.result
}
