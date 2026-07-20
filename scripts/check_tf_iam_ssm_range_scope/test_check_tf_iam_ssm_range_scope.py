"""Tests for check_tf_iam_ssm_range_scope.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_iam_ssm_range_scope.test_check_tf_iam_ssm_range_scope -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_iam_ssm_range_scope import check_file


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "iam.tf"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfIamSsmRangeScopeTest(unittest.TestCase):
    def test_env_and_range_wildcard_on_range_instance_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_ssm_params" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "ssm:PutParameter",
                          "ssm:GetParameter",
                          "ssm:DeleteParameter"
                        ]
                        Resource = "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter/shifter/*/range/*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("wildcard the environment" in r for r in reasons))
        self.assertTrue(any("concrete range id" in r for r in reasons))

    def test_env_scoped_range_wildcard_on_range_instance_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_ssm_params" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["ssm:GetParameter"]
                        Resource = "arn:aws:ssm:us-east-2:123:parameter/shifter/${var.environment}/range/*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("concrete range id" in r for r in reasons))
        # Environment segment is concrete here, so no env-wildcard violation.
        self.assertFalse(any("wildcard the environment" in r for r in reasons))

    def test_concrete_range_scope_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_ssm_params" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["ssm:GetParameter", "ssm:GetParameters"]
                        Resource = "arn:aws:ssm:us-east-2:123:parameter/shifter/${var.environment}/range/${var.range_id}/*"
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_provisioner_orchestrator_role_is_ignored(self) -> None:
        # The provisioner ECS task role legitimately holds an env-scoped
        # parameter/shifter/<env>/range/* grant. It is not a range-instance
        # (guest) role, so it must not be flagged.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ssm_parameters" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["ssm:PutParameter", "ssm:GetParameter"]
                        Resource = "arn:aws:ssm:us-east-2:123:parameter/shifter/${var.environment}/range/*"
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_non_ssm_statement_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_s3" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["s3:GetObject"]
                        Resource = "arn:aws:s3:::bucket/*"
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_ssm_wildcard_action_with_cross_range_resource_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_ssm_params" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["ssm:Get*"]
                        Resource = "arn:aws:ssm:us-east-2:123:parameter/shifter/*/range/*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(reasons)
        self.assertTrue(any("wildcard the environment" in r for r in reasons))

    def test_resource_list_form_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_ssm_params" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["ssm:GetParameter"]
                        Resource = [
                          "arn:aws:ssm:us-east-2:123:parameter/shifter/${var.environment}/range/${var.range_id}/*",
                          "arn:aws:ssm:us-east-2:123:parameter/shifter/*/range/*"
                        ]
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("wildcard the environment" in r for r in reasons))

    def test_ssm_parameter_action_with_resource_star_rejected(self) -> None:
        # Resource = "*" with an SSM parameter action grants access to every
        # range's parameters and must be flagged even though the ARN does not
        # literally contain parameter/shifter/.../range/.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_ssm_params" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["ssm:GetParameter"]
                        Resource = "*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("Resource=*" in r for r in reasons))

    def test_full_wildcard_action_with_resource_star_rejected(self) -> None:
        # Action = "*" covers ssm parameter actions; Resource = "*" makes it
        # cross-range. The checker must not fail open on the all-wildcard shape.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_admin" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = "*"
                        Resource = "*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("Resource=*" in r for r in reasons))

    def test_full_wildcard_action_with_cross_range_resource_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_admin" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = "*"
                        Resource = "arn:aws:ssm:us-east-2:123:parameter/shifter/*/range/*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [v.reason for v in check_file(tf)]

        self.assertTrue(any("wildcard the environment" in r for r in reasons))

    def test_non_ssm_action_with_resource_star_passes(self) -> None:
        # A non-SSM grant (no ssm action, no full wildcard) on Resource=* is
        # not in scope for this checker.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_s3" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["s3:GetObject"]
                        Resource = "*"
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_full_wildcard_action_with_concrete_range_resource_passes(self) -> None:
        # Action="*" is broad but the resource is bound to a concrete range id,
        # so it does not cross the range boundary that R17 guards.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "range_instance_admin" {
                  role = aws_iam_role.range_instance.id
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = "*"
                        Resource = "arn:aws:ssm:us-east-2:123:parameter/shifter/${var.environment}/range/${var.range_id}/*"
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_live_range_vpc_iam_module_passes(self) -> None:
        path = Path("platform/terraform/modules/range/vpc/iam.tf")

        self.assertEqual(check_file(path), [])


if __name__ == "__main__":
    unittest.main()
