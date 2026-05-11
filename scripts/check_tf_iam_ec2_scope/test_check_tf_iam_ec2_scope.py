"""Tests for check_tf_iam_ec2_scope.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_iam_ec2_scope.test_check_tf_iam_ec2_scope -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_iam_ec2_scope import check_file


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "iam.tf"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfIamEc2ScopeTest(unittest.TestCase):
    def test_wildcard_lifecycle_statement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ec2_provisioning" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "ec2:StartInstances",
                          "ec2:StopInstances",
                          "ec2:TerminateInstances",
                          "ec2:Describe*"
                        ]
                        Resource = "*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(any("must not use Resource=*" in reason for reason in reasons))
        self.assertTrue(
            any("must be scoped to EC2 instance ARNs" in reason for reason in reasons)
        )
        self.assertTrue(any("ec2:ResourceTag/shifter:system" in reason for reason in reasons))
        self.assertTrue(any("Describe APIs must stay separate" in reason for reason in reasons))

    def test_scoped_lifecycle_statement_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ec2_provisioning" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "EC2DescribeAndKeyPairOperations"
                        Action = [
                          "ec2:Describe*",
                          "ec2:ImportKeyPair",
                          "ec2:DeleteKeyPair"
                        ]
                        Resource = "*"
                      },
                      {
                        Sid = "EC2TaggedInstanceLifecycle"
                        Action = [
                          "ec2:StartInstances",
                          "ec2:StopInstances",
                          "ec2:TerminateInstances",
                          "ec2:ModifyInstanceAttribute",
                          "ec2:ModifyInstanceMetadataOptions"
                        ]
                        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
                        Condition = {
                          StringEquals = {
                            "ec2:ResourceTag/shifter:system"      = "shifter"
                            "ec2:ResourceTag/shifter:environment" = var.environment
                            "ec2:ResourceTag/ManagedBy"           = "terraform"
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_wildcard_lifecycle_action_pattern_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ec2_provisioning" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "ec2:*Instances"
                        ]
                        Resource = "*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(any("wildcard action patterns" in reason for reason in reasons))
        self.assertTrue(any("must not use Resource=*" in reason for reason in reasons))

    def test_current_engine_provisioner_policy_scopes_mutable_lifecycle_actions(self) -> None:
        path = Path("platform/terraform/modules/engine-provisioner/iam.tf")

        self.assertEqual(check_file(path), [])


if __name__ == "__main__":
    unittest.main()
