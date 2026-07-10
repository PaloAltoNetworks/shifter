"""Tests for check_tf_iam_role_naming.py."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_iam_role_naming import check_file


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfIamRoleNamingTest(unittest.TestCase):
    def test_iam_role_using_name_prefix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "main.tf",
                """
                resource "aws_iam_role" "this" {
                  name = "${var.name_prefix}-ec2-role"
                }
                """,
            )
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("iam_name_prefix" in reason for reason in reasons))

    def test_iam_role_using_iam_name_prefix_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "main.tf",
                """
                resource "aws_iam_role" "this" {
                  name = "${local.iam_name_prefix}-ec2-role"
                }
                """,
            )
            self.assertEqual(check_file(tf), [])

    def test_non_tf_inputs_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "lambda.zip"
            artifact.write_bytes(b"\x00\x8a\xff")

            self.assertEqual(check_file(artifact), [])

    def test_github_oidc_legacy_patterns_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "github-oidc.tf",
                """
                resource "aws_iam_policy" "iam_scoped" {
                  policy = jsonencode({
                    Statement = [{
                      Resource = ["arn:aws:iam::123:role/dev-portal-*"]
                    }]
                  })
                }
                """,
            )
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("legacy dev-portal" in reason for reason in reasons))

    def test_github_oidc_too_many_attachments_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachments = "\n".join(
                f'''
                resource "aws_iam_role_policy_attachment" "p{n}" {{
                  role       = aws_iam_role.github_actions.name
                  policy_arn = aws_iam_policy.p{n}.arn
                }}
                '''
                for n in range(7)
            )
            tf = _write(Path(tmp), "github-oidc.tf", attachments)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("at most" in reason for reason in reasons))

    def test_github_oidc_attachments_within_cap_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachments = "\n".join(
                f'''
                resource "aws_iam_role_policy_attachment" "p{n}" {{
                  role       = aws_iam_role.github_actions.name
                  policy_arn = aws_iam_policy.p{n}.arn
                }}
                '''
                for n in range(5)
            )
            tf = _write(Path(tmp), "github-oidc.tf", attachments)
            reasons = [v.reason for v in check_file(tf)]
        self.assertFalse(any("at most" in reason for reason in reasons))

    def test_github_oidc_oversized_policy_doc_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = ",\n".join(
                f'"service:VeryLongActionName{n:04d}"' for n in range(300)
            )
            tf = _write(
                Path(tmp),
                "github-oidc.tf",
                f"""
                resource "aws_iam_policy" "management" {{
                  policy = jsonencode({{
                    Statement = [{{
                      Action = [
                        {actions}
                      ]
                      Resource = "*"
                    }}]
                  }})
                }}
                """,
            )
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("size limit" in reason for reason in reasons))

    def test_github_oidc_policy_doc_within_limit_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "github-oidc.tf",
                """
                resource "aws_iam_policy" "management" {
                  policy = jsonencode({
                    Statement = [{
                      Action   = ["logs:CreateLogGroup", "logs:DeleteLogGroup"]
                      Resource = "*"
                    }]
                  })
                }
                """,
            )
            reasons = [v.reason for v in check_file(tf)]
        self.assertFalse(any("size limit" in reason for reason in reasons))

    def test_github_oidc_shifter_pattern_with_attach_allowlist_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "github-oidc.tf",
                """
                resource "aws_iam_policy" "iam_scoped" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["iam:PutRolePolicy"]
                        Resource = "arn:aws:iam::123:role/shifter-*"
                      },
                      {
                        Action = ["iam:AttachRolePolicy"]
                        Resource = "arn:aws:iam::123:role/shifter-*"
                        Condition = {
                          ArnEquals = {
                            "iam:PolicyArn" = [
                              "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
                              "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
                              "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                              "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
                            ]
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )
            self.assertEqual(check_file(tf), [])


if __name__ == "__main__":
    unittest.main()
