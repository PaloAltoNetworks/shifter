"""Tests for check_tf_iam_bedrock_agent_scope.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_iam_bedrock_agent_scope.test_check_tf_iam_bedrock_agent_scope -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_iam_bedrock_agent_scope import check_file

_GOOD_ROLE = """
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
"""

_GOOD_POLICY = """
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
"""


def _write(tmp_path: Path, *bodies: str) -> Path:
    path = tmp_path / "iam.tf"
    content = "\n".join(textwrap.dedent(body).strip() for body in bodies) + "\n"
    path.write_text(content)
    return path


class CheckTfIamBedrockAgentScopeTest(unittest.TestCase):
    def test_good_role_and_policy_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, _GOOD_POLICY)

            self.assertEqual(check_file(tf), [])

    def test_extra_s3_action_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            '"bedrock:InvokeModelWithResponseStream"\n        ]\n        Resource = [\n          var.polaris_agent_main_inference_profile_arn,',
            '"bedrock:InvokeModelWithResponseStream",\n          "s3:GetObject"\n        ]\n        Resource = [\n          var.polaris_agent_main_inference_profile_arn,',
        )
        self.assertIn("s3:GetObject", bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("s3:GetObject" in r for r in reasons))

    def test_bedrock_wildcard_action_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            'Action = [\n          "bedrock:InvokeModel",\n          "bedrock:InvokeModelWithResponseStream"\n        ]\n        Resource = [\n          var.polaris_agent_main_inference_profile_arn,',
            'Action = "bedrock:*"\n        Resource = [\n          var.polaris_agent_main_inference_profile_arn,',
        )
        self.assertIn('"bedrock:*"', bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("bedrock:*" in r for r in reasons))

    def test_action_star_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            'Action = [\n          "bedrock:InvokeModel",\n          "bedrock:InvokeModelWithResponseStream"\n        ]\n        Resource = [\n          var.polaris_agent_main_inference_profile_arn,',
            'Action = "*"\n        Resource = [\n          var.polaris_agent_main_inference_profile_arn,',
        )
        self.assertIn('Action = "*"', bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(reasons)

    def test_resource_star_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            "Resource = [\n          var.polaris_agent_main_inference_profile_arn,\n          var.polaris_agent_small_inference_profile_arn\n        ]",
            'Resource = "*"',
        )
        self.assertIn('Resource = "*"', bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("wildcard" in r for r in reasons))

    def test_unexpected_resource_variable_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            "var.polaris_agent_small_inference_profile_arn\n        ]\n      },\n      {\n        Sid    = \"InvokeBackingModelsViaApprovedProfiles\"",
            "var.polaris_agent_small_inference_profile_arn,\n          var.some_other_secret_arn\n        ]\n      },\n      {\n        Sid    = \"InvokeBackingModelsViaApprovedProfiles\"",
        )
        self.assertIn("var.some_other_secret_arn", bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("some_other_secret_arn" in r for r in reasons))

    def test_missing_inference_profile_arn_condition_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            """        Condition = {
          StringEquals = {
            "bedrock:InferenceProfileArn" = [
              var.polaris_agent_main_inference_profile_arn,
              var.polaris_agent_small_inference_profile_arn
            ]
          }
        }
""",
            "",
        )
        self.assertNotIn("bedrock:InferenceProfileArn", bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("InferenceProfileArn" in r for r in reasons))

    def test_trust_missing_source_instance_condition_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            """        Condition = {
          StringEquals = {
            "ec2:SourceInstanceARN" = aws_instance.range[local.polaris_agent_instance_key].arn
          }
        }
""",
            "",
        )
        self.assertNotIn("ec2:SourceInstanceARN", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("ec2:SourceInstanceARN" in r for r in reasons))

    def test_trust_principal_wildcard_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            "Principal = {\n          AWS = var.range_instance_role_arn\n        }",
            'Principal = "*"',
        )
        self.assertIn('Principal = "*"', bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("Principal" in r for r in reasons))

    def test_trust_principal_service_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            "Principal = {\n          AWS = var.range_instance_role_arn\n        }",
            'Principal = {\n          Service = "ec2.amazonaws.com"\n        }',
        )
        self.assertIn("Service", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("service principal" in r for r in reasons))

    def test_missing_permissions_boundary_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            "  permissions_boundary = var.polaris_agent_permissions_boundary_arn\n",
            "",
        )
        self.assertNotIn("permissions_boundary = var.polaris_agent_permissions_boundary_arn\n", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("must set permissions_boundary" in r for r in reasons))

    # -- Mandatory, unconditional permissions boundary (ADR-004-R21, codex
    # pre-push finding #1377 cycle 2) --
    #
    # The checker previously accepted the conditional expression
    # ``var.polaris_agent_permissions_boundary_arn != "" ? ... : null`` just
    # because it mentioned the variable, which let an enabled agent role
    # apply with permissions_boundary = null whenever the boundary variable
    # happened to be empty. These tests lock in the fixed contract: the
    # assignment must be unconditional, and the role's lifecycle.precondition
    # must independently enforce a non-empty boundary when enabled.

    def test_permissions_boundary_conditional_form_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            "  permissions_boundary = var.polaris_agent_permissions_boundary_arn\n",
            '  permissions_boundary = var.polaris_agent_permissions_boundary_arn != "" ? '
            "var.polaris_agent_permissions_boundary_arn : null\n",
        )
        self.assertIn("? var.polaris_agent_permissions_boundary_arn : null", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("unconditionally" in r for r in reasons))

    def test_permissions_boundary_null_literal_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            "  permissions_boundary = var.polaris_agent_permissions_boundary_arn\n",
            "  permissions_boundary = null\n",
        )
        self.assertIn("permissions_boundary = null", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("unconditionally" in r for r in reasons))

    def test_permissions_boundary_precondition_missing_non_empty_check_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            '        var.polaris_agent_permissions_boundary_arn != "" &&\n',
            "",
        )
        self.assertNotIn('polaris_agent_permissions_boundary_arn != ""', bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("precondition" in r.lower() and "permissions" in r.lower() for r in reasons))

    def test_permissions_boundary_fixed_form_passes(self) -> None:
        """The real (fixed) shape -- unconditional assignment plus a
        precondition enforcing non-empty -- produces zero violations."""
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, _GOOD_POLICY)

            self.assertEqual(check_file(tf), [])

    def test_missing_tags_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            """
  tags = merge(local.common_tags, {
    Name              = local.polaris_agent_role_name
    "shifter:purpose" = "polaris-agent"
  })
""",
            "\n",
        )
        self.assertNotIn("tags", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("tags" in r for r in reasons))

    def test_unrelated_resource_ignored(self) -> None:
        # The protected polaris_agent role/policy must still be present (the
        # checker now fails closed when they are absent -- see
        # test_role_resource_missing_rejected /
        # test_policy_resource_missing_rejected below), but an unrelated
        # resource sharing the file must not itself trigger a violation.
        unrelated = """
        resource "aws_iam_role" "range_instance" {
          name = "range-instance"
          assume_role_policy = jsonencode({
            Statement = [
              {
                Effect = "Allow"
                Action = "sts:AssumeRole"
                Principal = {
                  Service = "ec2.amazonaws.com"
                }
              }
            ]
          })
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, _GOOD_POLICY, unrelated)

            self.assertEqual(check_file(tf), [])

    def test_live_iam_module_passes(self) -> None:
        path = Path("shifter/engine/provisioner/terraform/modules/range/iam.tf")

        self.assertEqual(check_file(path), [])

    # -- Fail-closed regression coverage (codex pre-push finding, #1377) --
    #
    # The checker previously only validated aws_iam_role /
    # aws_iam_role_policy blocks it happened to find named "polaris_agent".
    # Deleting, renaming, or emptying those resources -- or writing their
    # Action/Resource fields as an expression the regex parser doesn't
    # recognize -- produced zero violations (a silent pass) instead of an
    # explicit failure. These tests lock in the fail-closed behavior.

    def test_role_resource_missing_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any('"aws_iam_role" "polaris_agent" not found' in r for r in reasons))

    def test_role_resource_renamed_rejected(self) -> None:
        renamed_role = _GOOD_ROLE.replace(
            'resource "aws_iam_role" "polaris_agent" {',
            'resource "aws_iam_role" "polaris_agent_v2" {',
        )
        self.assertIn('"polaris_agent_v2"', renamed_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), renamed_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any('"aws_iam_role" "polaris_agent" not found' in r for r in reasons))

    def test_policy_resource_missing_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(
            any('"aws_iam_role_policy" "polaris_agent" not found' in r for r in reasons)
        )

    def test_policy_resource_renamed_rejected(self) -> None:
        renamed_policy = _GOOD_POLICY.replace(
            'resource "aws_iam_role_policy" "polaris_agent" {',
            'resource "aws_iam_role_policy" "polaris_agent_v2" {',
        )
        self.assertIn('"polaris_agent_v2"', renamed_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, renamed_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(
            any('"aws_iam_role_policy" "polaris_agent" not found' in r for r in reasons)
        )

    def test_policy_resource_emptied_rejected(self) -> None:
        emptied_policy = """
        resource "aws_iam_role_policy" "polaris_agent" {
          count = var.polaris_agent_enabled ? 1 : 0

          name = "bedrock-invoke"
          role = aws_iam_role.polaris_agent[0].id
        }
        """
        self.assertNotIn("jsonencode", emptied_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, emptied_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("missing required action" in r.lower() for r in reasons))

    def test_policy_missing_resource_field_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            "Resource = [\n          var.polaris_agent_main_inference_profile_arn,"
            "\n          var.polaris_agent_small_inference_profile_arn\n        ]\n      },",
            "      },",
        )
        self.assertNotIn(
            "var.polaris_agent_main_inference_profile_arn,\n          "
            "var.polaris_agent_small_inference_profile_arn",
            bad_policy,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("missing a Resource field" in r for r in reasons))

    def test_unparseable_action_expression_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            'Action = [\n          "bedrock:InvokeModel",\n          '
            '"bedrock:InvokeModelWithResponseStream"\n        ]\n        Resource = [\n'
            "          var.polaris_agent_main_inference_profile_arn,",
            "Action = local.polaris_agent_allowed_actions\n        Resource = [\n"
            "          var.polaris_agent_main_inference_profile_arn,",
        )
        self.assertIn("local.polaris_agent_allowed_actions", bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(
            any("Action" in r and "could not be resolved" in r for r in reasons)
        )

    def test_unparseable_resource_expression_rejected(self) -> None:
        bad_policy = _GOOD_POLICY.replace(
            "Resource = [\n          var.polaris_agent_main_inference_profile_arn,"
            "\n          var.polaris_agent_small_inference_profile_arn\n        ]",
            "Resource = local.polaris_agent_allowed_resources",
        )
        self.assertIn("local.polaris_agent_allowed_resources", bad_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, bad_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(
            any("Resource" in r and "could not be resolved" in r for r in reasons)
        )

    # -- Additional policy surfaces on the protected role (codex pre-push
    # finding, #1377 cycle 3) --
    #
    # The checker previously recognized only aws_iam_role /
    # aws_iam_role_policy and validated only the single INLINE policy named
    # "polaris_agent". A second aws_iam_role_policy under any other name
    # whose ``role`` argument targets aws_iam_role.polaris_agent, or a
    # managed-policy attachment (aws_iam_role_policy_attachment /
    # aws_iam_role_managed_policy_attachment / an inline
    # managed_policy_arns list on the role itself), would grant the
    # participant's STS credentials extra permissions up to the account
    # boundary while the canonical narrow inline policy stayed unchanged
    # and the guard stayed green. These tests lock in that any such
    # additional policy surface targeting the protected role is rejected.

    def test_extra_inline_policy_on_role_rejected(self) -> None:
        extra_policy = """
        resource "aws_iam_role_policy" "polaris_agent_extra" {
          count = var.polaris_agent_enabled ? 1 : 0

          name = "extra-permissions"
          role = aws_iam_role.polaris_agent.id

          policy = jsonencode({
            Version = "2012-10-17"
            Statement = [
              {
                Effect   = "Allow"
                Action   = "s3:*"
                Resource = "*"
              }
            ]
          })
        }
        """
        self.assertIn("aws_iam_role.polaris_agent.id", extra_policy)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, _GOOD_POLICY, extra_policy)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("extra_inline_policy_on_role" in r for r in reasons))

    def test_managed_policy_attachment_on_role_rejected(self) -> None:
        attachment = """
        resource "aws_iam_role_policy_attachment" "polaris_agent_admin" {
          count = var.polaris_agent_enabled ? 1 : 0

          role       = aws_iam_role.polaris_agent.name
          policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
        }
        """
        self.assertIn("aws_iam_role.polaris_agent.name", attachment)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _GOOD_ROLE, _GOOD_POLICY, attachment)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("managed_policy_attachment_on_role" in r for r in reasons))

    def test_managed_policy_arns_on_role_rejected(self) -> None:
        bad_role = _GOOD_ROLE.replace(
            "  permissions_boundary = var.polaris_agent_permissions_boundary_arn\n",
            "  permissions_boundary = var.polaris_agent_permissions_boundary_arn\n"
            '  managed_policy_arns  = ["arn:aws:iam::aws:policy/AdministratorAccess"]\n',
        )
        self.assertIn("managed_policy_arns", bad_role)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), bad_role, _GOOD_POLICY)

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("managed_policy_arns_on_role" in r for r in reasons))

    def test_unrelated_policy_and_attachment_ignored(self) -> None:
        """A second inline policy or attachment that targets a DIFFERENT
        role must not trip the new checks (only ones targeting
        aws_iam_role.polaris_agent are in scope)."""
        unrelated_policy = """
        resource "aws_iam_role_policy" "range_instance_extra" {
          name = "range-instance-extra"
          role = aws_iam_role.range_instance.id

          policy = jsonencode({
            Version = "2012-10-17"
            Statement = [
              {
                Effect   = "Allow"
                Action   = "s3:GetObject"
                Resource = "*"
              }
            ]
          })
        }
        """
        unrelated_attachment = """
        resource "aws_iam_role_policy_attachment" "range_instance_admin" {
          role       = aws_iam_role.range_instance.name
          policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp), _GOOD_ROLE, _GOOD_POLICY, unrelated_policy, unrelated_attachment
            )

            self.assertEqual(check_file(tf), [])

    def test_live_iam_module_has_no_extra_policy_surfaces(self) -> None:
        """Regression guard: the real module's single-canonical-policy,
        no-attachments shape must not false-positive on the new checks."""
        path = Path("shifter/engine/provisioner/terraform/modules/range/iam.tf")

        self.assertEqual(check_file(path), [])


if __name__ == "__main__":
    unittest.main()
