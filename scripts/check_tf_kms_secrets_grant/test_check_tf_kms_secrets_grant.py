"""Tests for check_tf_kms_secrets_grant.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_kms_secrets_grant.test_check_tf_kms_secrets_grant -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_kms_secrets_grant import check_file


def _write(tmp_path: Path, body: str, name: str = "iam.tf") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfKmsSecretsGrantTest(unittest.TestCase):
    def test_role_that_reads_secrets_manager_without_kms_grant_is_rejected(self) -> None:
        # Live state of dev-portal-pulumi-ecs-execution and
        # dev-portal-ec2-role before this PR — they have
        # secretsmanager:GetSecretValue but no kms:Decrypt grant.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_execution" {
                  name = "dev-portal-pulumi-ecs-execution"
                }

                resource "aws_iam_role_policy" "ecs_execution_secrets" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = [aws_secretsmanager_secret.dc_domain_password.arn]
                    }]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "no attached aws_iam_role_policy satisfies" in reason
                for reason in reasons
            ),
            f"expected missing-grant violation, got: {reasons}",
        )

    def test_role_that_does_not_read_secrets_manager_is_not_required_to_have_grant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "log_writer" {
                  name = "dev-portal-log-writer"
                }

                resource "aws_iam_role_policy" "logs" {
                  role = aws_iam_role.log_writer.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
                      Resource = "*"
                    }]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_unconditioned_wildcard_kms_decrypt_is_rejected(self) -> None:
        # kms:Decrypt on Resource="*" without a kms:ViaService
        # condition is unconditioned wildcard access; the shape check
        # rejects it regardless of whether the role reads Secrets
        # Manager. kms:Decrypt scoped to a specific KMS key ARN
        # without a condition is fine (the key's resource ARN is the
        # boundary).
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "broken" {
                  name = "broken-role"
                }

                resource "aws_iam_role_policy" "broken_kms" {
                  role = aws_iam_role.broken.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["kms:Decrypt"]
                      Resource = "*"
                    }]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("kms:ViaService" in reason for reason in reasons),
            f"expected wildcard ViaService-condition violation, got: {reasons}",
        )

    def test_specific_key_kms_decrypt_without_via_service_passes(self) -> None:
        # A grant scoped to a specific KMS key ARN (e.g.
        # var.engine_secrets_kms_key_arn for the engine's awskms:// path)
        # without a kms:ViaService condition is fine — the key's
        # resource ARN is the boundary. Mirrors the existing
        # EngineSecretsEncryption statement on the provisioner task role.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "engine" {
                  name = "engine-role"
                }

                resource "aws_iam_role_policy" "engine_secrets_kms" {
                  role = aws_iam_role.engine.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Sid    = "EngineSecretsEncryption"
                      Effect = "Allow"
                      Action = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
                      Resource = var.engine_secrets_kms_key_arn
                    }]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_correctly_scoped_kms_decrypt_grant_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_execution" {
                  name = "dev-portal-pulumi-ecs-execution"
                }

                resource "aws_iam_role_policy" "ecs_execution_secrets" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = [aws_secretsmanager_secret.dc_domain_password.arn]
                    }]
                  })
                }

                resource "aws_iam_role_policy" "ecs_execution_kms" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Sid    = "SecretsManagerKMSAccess"
                      Effect = "Allow"
                      Action = ["kms:Decrypt", "kms:DescribeKey"]
                      Resource = var.secrets_manager_kms_key_arn
                      Condition = {
                        StringEquals = {
                          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
                        }
                      }
                    }]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_wildcard_resource_with_secretsmanager_via_service_passes(self) -> None:
        # The existing engine-provisioner task role uses Resource="*"
        # gated by kms:ViaService=secretsmanager — this is broader than
        # the new grants but still safe (the service condition pins
        # Secrets Manager as the only caller). The checker MUST NOT
        # regress that pattern.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_task" {
                  name = "dev-portal-pulumi-ecs-task"
                }

                resource "aws_iam_role_policy" "secrets_manager" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect = "Allow"
                      Action = ["secretsmanager:GetSecretValue"]
                      Resource = ["arn:aws:secretsmanager:us-east-2:0:secret:shifter/dev/range/*"]
                    }]
                  })
                }

                resource "aws_iam_role_policy" "kms" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Sid    = "SecretsManagerKMSAccess"
                      Effect = "Allow"
                      Action = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
                      Resource = "*"
                      Condition = {
                        StringEquals = {
                          "kms:ViaService" = "secretsmanager.${local.region}.amazonaws.com"
                        }
                      }
                    }]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_file_without_iam_role_definition_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy_attachment" "x" {
                  role       = aws_iam_role.somewhere_else.name
                  policy_arn = "arn:aws:iam::aws:policy/SomePolicy"
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_role_using_another_roles_grant_does_not_count(self) -> None:
        # Two roles, both with secretsmanager:GetSecretValue, but the
        # kms:Decrypt grant is only attached to one. The other must still
        # be flagged.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_execution" {
                  name = "dev-portal-pulumi-ecs-execution"
                }

                resource "aws_iam_role" "ecs_task" {
                  name = "dev-portal-pulumi-ecs-task"
                }

                resource "aws_iam_role_policy" "exec_secrets" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = "*"
                    }]
                  })
                }

                resource "aws_iam_role_policy" "task_secrets" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = "*"
                    }]
                  })
                }

                resource "aws_iam_role_policy" "task_kms" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect = "Allow"
                      Action = ["kms:Decrypt"]
                      Resource = var.secrets_manager_kms_key_arn
                      Condition = {
                        StringEquals = {
                          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
                        }
                      }
                    }]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "ecs_execution" in reason
                and "no attached aws_iam_role_policy satisfies" in reason
                for reason in reasons
            ),
            f"expected ecs_execution missing-grant violation, got: {reasons}",
        )

    def test_substring_var_name_does_not_satisfy(self) -> None:
        # var.engine_secrets_kms_key_arn contains var.secrets_kms_key_arn
        # as a substring. The exact-token regex must reject the wrong
        # CMK var even when a Secrets Manager ViaService condition is
        # present.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_task" {
                  name = "dev-portal-pulumi-ecs-task"
                }

                resource "aws_iam_role_policy" "secrets" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = "*"
                    }]
                  })
                }

                resource "aws_iam_role_policy" "wrong_cmk" {
                  role = aws_iam_role.ecs_task.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect = "Allow"
                      Action = ["kms:Decrypt"]
                      Resource = var.engine_secrets_kms_key_arn
                      Condition = {
                        StringEquals = {
                          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
                        }
                      }
                    }]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "no attached aws_iam_role_policy satisfies" in reason
                for reason in reasons
            ),
            f"expected substring-match rejection of wrong-CMK grant, got: {reasons}",
        )

    def test_via_service_substring_outside_condition_does_not_satisfy(self) -> None:
        # The kms:ViaService string appears in Sid free-text but not in
        # any Condition. A substring matcher would incorrectly pass.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_execution" {
                  name = "dev-portal-pulumi-ecs-execution"
                }

                resource "aws_iam_role_policy" "exec_secrets" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = "*"
                    }]
                  })
                }

                resource "aws_iam_role_policy" "exec_kms" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Sid    = "TODO: add kms:ViaService = secretsmanager.* condition"
                      Effect = "Allow"
                      Action = ["kms:Decrypt"]
                      Resource = var.secrets_manager_kms_key_arn
                    }]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "no attached aws_iam_role_policy satisfies" in reason
                for reason in reasons
            ),
            f"expected missing-grant violation for ViaService outside Condition, got: {reasons}",
        )

    def test_via_service_in_wrong_condition_operator_does_not_satisfy(self) -> None:
        # A `kms:ViaService` value in StringNotEquals (instead of
        # StringEquals/StringLike) does NOT pin the call to Secrets
        # Manager. The matcher only counts the right operator types.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role" "ecs_execution" {
                  name = "dev-portal-pulumi-ecs-execution"
                }

                resource "aws_iam_role_policy" "exec_secrets" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["secretsmanager:GetSecretValue"]
                      Resource = "*"
                    }]
                  })
                }

                resource "aws_iam_role_policy" "exec_kms" {
                  role = aws_iam_role.ecs_execution.id
                  policy = jsonencode({
                    Version = "2012-10-17"
                    Statement = [{
                      Effect   = "Allow"
                      Action   = ["kms:Decrypt"]
                      Resource = var.secrets_manager_kms_key_arn
                      Condition = {
                        StringNotEquals = {
                          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
                        }
                      }
                    }]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "no attached aws_iam_role_policy satisfies" in reason
                for reason in reasons
            ),
            f"expected missing-grant violation for wrong condition operator, got: {reasons}",
        )

    def test_live_provisioner_iam_tf_has_execution_role_kms_grant(self) -> None:
        # Live-state regression: after this PR lands, the provisioner ECS
        # execution role (which has secretsmanager:GetSecretValue via
        # ecs_execution_secrets) must have a Secrets Manager kms:Decrypt
        # grant attached.
        path = Path("platform/terraform/modules/engine-provisioner/iam.tf")
        self.assertEqual(check_file(path), [])

    def test_live_portal_ec2_main_tf_has_kms_grant(self) -> None:
        # Live-state regression: after this PR lands, the portal EC2 role
        # (which has secretsmanager:GetSecretValue via secrets_read +
        # range_ssh_keys + ngfw_ssh_keys) must have the same grant.
        path = Path("platform/terraform/modules/portal/ec2/main.tf")
        self.assertEqual(check_file(path), [])

    def test_live_guacamole_iam_tf_has_kms_grants(self) -> None:
        # Live-state regression: the guacamole module encrypts its DB
        # credentials + JSON auth secrets with the same portal CMK
        # (rds.tf:36, rds.tf:73) and gives its ECS execution role +
        # client task role secretsmanager:GetSecretValue. Both need the
        # matching kms:Decrypt grant or the same #52-class failure
        # recurs on the next guacamole secret rotation.
        path = Path("platform/terraform/modules/guacamole/iam.tf")
        self.assertEqual(check_file(path), [])


if __name__ == "__main__":
    unittest.main()
