# ------------------------------------------------------------------------------
# Secrets Manager
# ------------------------------------------------------------------------------
# Reference to the prebaked Domain Controller's Administrator password.
# The secret container AND its value are created out-of-band BEFORE
# `terraform apply` runs (see "Bootstrap (fresh environment)" in
# shifter/shifter_platform/documentation/docs/technical/dev/secrets.md).
# Terraform reads the existing secret via `data` rather than creating it,
# which avoids the chicken-and-egg case where the same apply that creates
# the empty secret container also stands up an ASG whose launch hook
# requires the value — the ASG would ABANDON every first launch until the
# operator seeded the value, which is not a recoverable bootstrap.
#
# Operator pre-bootstrap step (one-time per environment):
#   aws secretsmanager create-secret \
#     --name "shifter-${env}-portal-dc-domain" \
#     --description "Prebaked DC Administrator password" \
#     --secret-string "$DC_DOMAIN_PASSWORD"
#
# After that, `terraform apply` resolves the secret ARN, wires it into
# the engine provisioner ECS task (via `secrets = [...]` in
# task_definition.tf) and into the portal Django container (via the
# portal/ssm + portal/ec2 modules and entrypoint.sh).
#
# Rotation / value updates use `aws secretsmanager put-secret-value`;
# Terraform never touches the value, so the cleartext credential never
# lands in Terraform state.

data "aws_secretsmanager_secret" "dc_domain_password" {
  name = "shifter-${var.environment}-portal-dc-domain"
}
