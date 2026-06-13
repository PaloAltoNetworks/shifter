"""Tests for check_tf_rds_security.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_rds_security.test_check_tf_rds_security -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_rds_security import check_file


def _write(tmp_path: Path, body: str, name: str = "rds.tf") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfRdsSecurityTest(unittest.TestCase):
    def test_rds_instance_without_iam_auth_or_ca_identifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_instance" "db" {
                  identifier = "example"
                  engine     = "postgres"
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertIn("missing iam_database_authentication_enabled = true", reasons)
        self.assertIn("missing ca_cert_identifier", reasons)

    def test_rds_instance_with_disabled_iam_auth_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_instance" "db" {
                  identifier                              = "example"
                  iam_database_authentication_enabled     = false
                  ca_cert_identifier                      = var.rds_ca_cert_identifier
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertIn(
            "iam_database_authentication_enabled must be literal true",
            reasons,
        )

    def test_rds_instance_with_variable_iam_auth_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_instance" "db" {
                  identifier                          = "example"
                  iam_database_authentication_enabled = var.rds_iam_auth
                  ca_cert_identifier                  = var.rds_ca_cert_identifier
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertIn(
            "iam_database_authentication_enabled must be literal true",
            reasons,
        )

    def test_rds_instance_with_empty_ca_identifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_instance" "db" {
                  identifier                          = "example"
                  iam_database_authentication_enabled = true
                  ca_cert_identifier                  = ""
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertIn("ca_cert_identifier must not be empty or null", reasons)

    def test_rds_instance_with_null_ca_identifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_instance" "db" {
                  identifier                          = "example"
                  iam_database_authentication_enabled = true
                  ca_cert_identifier                  = null
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertIn("ca_cert_identifier must not be empty or null", reasons)

    def test_rds_instance_with_iam_auth_and_ca_identifier_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_instance" "db" {
                  identifier                          = "example"
                  iam_database_authentication_enabled = true
                  ca_cert_identifier                  = var.rds_ca_cert_identifier
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_non_rds_resources_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_db_parameter_group" "db" {
                  name = "example"
                }
                """,
            )

            self.assertEqual(check_file(tf), [])
