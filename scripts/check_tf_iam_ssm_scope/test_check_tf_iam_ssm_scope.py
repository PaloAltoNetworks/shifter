"""Tests for check_tf_iam_ssm_scope.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_iam_ssm_scope.test_check_tf_iam_ssm_scope -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_iam_ssm_scope import check_file

# Independent literals — NOT imported from the module under test — so that
# dropping a key from the checker's REQUIRED_*_TAG_KEYS (which silently
# re-widens the policy) makes the checker stop raising the violation and fails
# these tests. Deriving the expectation from the checker's own constant would be
# a tautology that cannot catch removal.
EXPECTED_SEND_COMMAND_TAG_KEYS = (
    "ssm:resourceTag/shifter:system",
    "ssm:resourceTag/shifter:environment",
    "ssm:resourceTag/shifter:range_id",
)
EXPECTED_REBOOT_TAG_KEYS = (
    "ec2:ResourceTag/shifter:system",
    "ec2:ResourceTag/shifter:environment",
    "ec2:ResourceTag/ManagedBy",
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "iam.tf"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfIamSsmScopeTest(unittest.TestCase):
    def test_wildcard_send_command_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ssm_run_command" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "ssm:SendCommand"
                        ]
                        Resource = "*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("ssm:SendCommand must not use Resource=*" in reason for reason in reasons)
        )

    def test_unconditioned_instance_send_command_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ssm_run_command" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "ssm:SendCommand"
                        ]
                        Resource = [
                          "arn:aws:ec2:${local.region}:${local.account_id}:instance/*",
                          "arn:aws:ssm:${local.region}::document/AWS-RunShellScript"
                        ]
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        # Assert a violation is raised for *every* required SendCommand tag key,
        # so dropping any key from REQUIRED_SEND_COMMAND_TAG_KEYS (which would
        # silently re-widen instance targeting) fails this test.
        for tag_key in EXPECTED_SEND_COMMAND_TAG_KEYS:
            self.assertTrue(
                any(tag_key in reason for reason in reasons),
                f"expected a violation requiring {tag_key}",
            )

    def test_unconditioned_reboot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ssm_run_command" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "ec2:RebootInstances"
                        ]
                        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        # Assert a reboot violation is raised for *every* required reboot tag
        # key, so dropping any key from REQUIRED_REBOOT_TAG_KEYS fails this test.
        for tag_key in EXPECTED_REBOOT_TAG_KEYS:
            self.assertTrue(
                any(
                    "ec2:RebootInstances" in reason and tag_key in reason
                    for reason in reasons
                ),
                f"expected a reboot violation requiring {tag_key}",
            )

    def test_scoped_policy_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "ssm_run_command" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "SendCommandToRangeInstances"
                        Action = [
                          "ssm:SendCommand"
                        ]
                        Resource = [
                          "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "ssm:resourceTag/shifter:system"      = "shifter"
                            "ssm:resourceTag/shifter:environment" = var.environment
                          }
                          Null = {
                            "ssm:resourceTag/shifter:range_id" = "false"
                          }
                        }
                      },
                      {
                        Sid = "SendCommandWithManagedDocuments"
                        Action = [
                          "ssm:SendCommand"
                        ]
                        Resource = [
                          "arn:aws:ssm:${local.region}::document/AWS-RunPowerShellScript",
                          "arn:aws:ssm:${local.region}::document/AWS-RunShellScript"
                        ]
                      },
                      {
                        Sid = "PollCommandResults"
                        Action = [
                          "ssm:GetCommandInvocation",
                          "ssm:ListCommandInvocations",
                          "ssm:DescribeInstanceInformation"
                        ]
                        Resource = "*"
                      },
                      {
                        Sid = "RebootRangeInstances"
                        Action = [
                          "ec2:RebootInstances"
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

    def test_current_engine_provisioner_policy_scopes_ssm_run_command(self) -> None:
        path = Path("platform/terraform/modules/engine-provisioner/iam.tf")

        self.assertEqual(check_file(path), [])


if __name__ == "__main__":
    unittest.main()
