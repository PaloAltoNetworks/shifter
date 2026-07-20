#------------------------------------------------------------------------------
# Per-Range Polaris Bedrock Agent Role (#1377)
#
# This role is the participant-facing AWS credential for the a14-kali
# container on a Polaris range host. It is deliberately NOT attached to
# any EC2 instance profile: the Polaris range host assumes it for
# short-lived STS sessions and hands only the resulting temporary
# credentials to the container. The EC2 instance profile
# (var.instance_profile_name, wired from the shared range-host role in
# platform/terraform/modules/range/vpc/iam.tf) remains the separate host
# operations identity used for SSM/S3.
#
# Trust is bound to the shared range-host role AND the exact Polaris EC2
# source instance (ec2:SourceInstanceARN), so no other range host --
# including another Polaris range's host -- can assume this role even
# though the shared role's own IAM policy allows it to assume anything
# in the shifter-${environment}-*-polaris-agent namespace.
#
# See docs/architecture/polaris-aws-agent-credentials-preflight-1377.md.
#------------------------------------------------------------------------------

locals {
  # IAM role names are capped at 64 characters. When the environment name
  # and range id would overflow that limit, truncate the variable portion
  # and append a short deterministic hash so two long/colliding names
  # cannot truncate onto the same role name (mirrors the
  # substr(<uuid>, 0, 8) truncation already used for per-instance secret
  # names in main.tf).
  polaris_agent_suffix    = "-polaris-agent"
  polaris_agent_name_base = "shifter-${var.environment}-range-${var.range_id}"
  polaris_agent_name_full = "${local.polaris_agent_name_base}${local.polaris_agent_suffix}"
  polaris_agent_name_hash = substr(sha1(local.polaris_agent_name_base), 0, 8)
  polaris_agent_role_name = length(local.polaris_agent_name_full) <= 64 ? local.polaris_agent_name_full : "${substr(local.polaris_agent_name_base, 0, 64 - length(local.polaris_agent_suffix) - length(local.polaris_agent_name_hash) - 1)}-${local.polaris_agent_name_hash}${local.polaris_agent_suffix}"

  # The Polaris scenario provisions exactly one attacker/kali instance per
  # range. role == "attacker" is not unique across every scenario (e.g.
  # TechVault also uses role == "attacker"), but polaris_agent_enabled is
  # only ever set true for a Polaris range, so within an enabled range
  # exactly one attacker instance is expected. The list is forced empty
  # when the feature is disabled so a non-Polaris range that happens to
  # have its own attacker instance never trips the one() cardinality
  # check below.
  polaris_agent_attacker_keys = var.polaris_agent_enabled ? [
    for k, inst in local.instance_map : k if inst.role == "attacker"
  ] : []
  polaris_agent_instance_key = one(local.polaris_agent_attacker_keys)
}

resource "aws_iam_role" "polaris_agent" {
  count = var.polaris_agent_enabled ? 1 : 0

  name                 = local.polaris_agent_role_name
  permissions_boundary = var.polaris_agent_permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = var.range_instance_role_arn
        }
        Condition = {
          StringEquals = {
            "ec2:SourceInstanceARN" = aws_instance.range[local.polaris_agent_instance_key].arn
          }
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name              = local.polaris_agent_role_name
    "shifter:purpose" = "polaris-agent"
  })

  # Fail closed at plan time: an enabled agent role with a missing trust
  # principal, an incomplete Bedrock target set, or no permissions boundary
  # would otherwise apply successfully and produce either a broken trust
  # policy, a role that cannot invoke any approved model, or (ADR-004-R21) an
  # enabled role with no permissions boundary at all.
  lifecycle {
    precondition {
      condition = (
        var.range_instance_role_arn != "" &&
        var.polaris_agent_main_inference_profile_arn != "" &&
        var.polaris_agent_small_inference_profile_arn != "" &&
        var.polaris_agent_permissions_boundary_arn != "" &&
        length(var.polaris_agent_main_backing_model_arns) > 0 &&
        length(var.polaris_agent_small_backing_model_arns) > 0
      )
      error_message = "polaris_agent_enabled requires range_instance_role_arn, both inference-profile ARNs, a non-empty permissions boundary ARN, and both backing-model ARN lists to be non-empty."
    }
  }
}

# Exactly the proven invocation actions against the approved inference
# profiles and their backing foundation models. No S3, SSM, IAM, KMS,
# Secrets Manager, arbitrary STS, or wildcard Bedrock access.
resource "aws_iam_role_policy" "polaris_agent" {
  count = var.polaris_agent_enabled ? 1 : 0

  name = "bedrock-invoke"
  role = aws_iam_role.polaris_agent[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeApprovedInferenceProfiles"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          var.polaris_agent_main_inference_profile_arn,
          var.polaris_agent_small_inference_profile_arn
        ]
      },
      {
        # Backing foundation models are reachable ONLY through the
        # approved inference profiles above, not directly, so a
        # participant cannot invoke them outside the approved profile.
        Sid    = "InvokeBackingModelsViaApprovedProfiles"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = concat(
          var.polaris_agent_main_backing_model_arns,
          var.polaris_agent_small_backing_model_arns
        )
        Condition = {
          StringEquals = {
            "bedrock:InferenceProfileArn" = [
              var.polaris_agent_main_inference_profile_arn,
              var.polaris_agent_small_inference_profile_arn
            ]
          }
        }
      }
    ]
  })
}
