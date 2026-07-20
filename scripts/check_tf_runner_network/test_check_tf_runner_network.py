"""Tests for check_tf_runner_network.py."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_runner_network import check_file

GUARDED = """
data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

data "aws_subnet" "runner" {
  id = var.subnet_id
}

resource "aws_security_group" "runner" {
  vpc_id = var.vpc_id

  lifecycle {
    precondition {
      condition     = !contains(data.aws_vpcs.default.ids, var.vpc_id)
      error_message = "no default vpc"
    }
    precondition {
      condition     = data.aws_subnet.runner.vpc_id == var.vpc_id
      error_message = "subnet must belong to vpc"
    }
  }
}
"""

# The real shape after the ADR-004-R20 escape hatch: preconditions reference the
# resolved local.runner_vpc_id and carry the explicit var.allow_default_vpc
# opt-in prefix. The guard is still present and fail-closed by default, so this
# must PASS.
GUARDED_ESCAPE_HATCH = """
data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

data "aws_subnet" "runner" {
  id = local.runner_subnet_id
}

resource "aws_security_group" "runner" {
  vpc_id = local.runner_vpc_id

  lifecycle {
    precondition {
      condition     = var.allow_default_vpc || !contains(data.aws_vpcs.default.ids, local.runner_vpc_id)
      error_message = "no default vpc unless opted in"
    }
    precondition {
      condition     = data.aws_subnet.runner.vpc_id == local.runner_vpc_id
      error_message = "subnet must belong to vpc"
    }
  }
}
"""

# Default-VPC guard present but the subnet-membership precondition removed.
NO_SUBNET_GUARD = """
data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

resource "aws_security_group" "runner" {
  vpc_id = var.vpc_id

  lifecycle {
    precondition {
      condition     = !contains(data.aws_vpcs.default.ids, var.vpc_id)
      error_message = "no default vpc"
    }
  }
}
"""

# Same stack with the default-VPC guard removed.
UNGUARDED = """
resource "aws_security_group" "runner" {
  vpc_id = var.vpc_id
}
"""

# Data source present but both fail-closed preconditions deleted: violations.
DATA_ONLY = """
data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

resource "aws_security_group" "runner" {
  vpc_id = var.vpc_id
}
"""

# Both preconditions present but the default-VPC data source declaration removed:
# isolates check 1 (the data source) so deleting it alone fails a test.
NO_DATA_SOURCE = """
resource "aws_security_group" "runner" {
  vpc_id = var.vpc_id

  lifecycle {
    precondition {
      condition     = !contains(data.aws_vpcs.default.ids, var.vpc_id)
      error_message = "no default vpc"
    }
    precondition {
      condition     = data.aws_subnet.runner.vpc_id == var.vpc_id
      error_message = "subnet must belong to vpc"
    }
  }
}
"""

# Data source and subnet-membership precondition present, but the default-VPC
# precondition removed: isolates check 2 so deleting it alone fails a test.
NO_DEFAULT_VPC_GUARD = """
data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

data "aws_subnet" "runner" {
  id = var.subnet_id
}

resource "aws_security_group" "runner" {
  vpc_id = var.vpc_id

  lifecycle {
    precondition {
      condition     = data.aws_subnet.runner.vpc_id == var.vpc_id
      error_message = "subnet must belong to vpc"
    }
  }
}
"""


def _write(tmp: str, name: str, body: str) -> Path:
    path = Path(tmp) / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfRunnerNetworkTest(unittest.TestCase):
    def test_guarded_runner_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", GUARDED)
            self.assertEqual(check_file(tf), [])

    def test_escape_hatch_form_passes(self) -> None:
        # The ADR-004-R20 opt-in prefix + resolved local.runner_vpc_id form is a
        # documented, non-silent way to accept default-VPC placement; the guard
        # is still present, so the checker must accept it.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", GUARDED_ESCAPE_HATCH)
            self.assertEqual(check_file(tf), [])

    def test_missing_guard_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", UNGUARDED)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("default VPC" in reason for reason in reasons))
        self.assertTrue(any("fail closed" in reason for reason in reasons))

    def test_data_source_without_precondition_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", DATA_ONLY)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("fail closed" in reason for reason in reasons))
        self.assertFalse(any("must declare" in reason for reason in reasons))

    def test_missing_subnet_membership_precondition_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", NO_SUBNET_GUARD)
            reasons = [v.reason for v in check_file(tf)]
        # The default-VPC half is satisfied; only the subnet-membership half fails.
        self.assertTrue(any("does not belong" in reason for reason in reasons))
        self.assertFalse(any("default-VPC placement" in reason for reason in reasons))
        self.assertFalse(any("must declare" in reason for reason in reasons))

    def test_missing_data_source_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", NO_DATA_SOURCE)
            reasons = [v.reason for v in check_file(tf)]
        # Only check 1 (the data source) fails; both preconditions are present.
        self.assertTrue(any("must declare" in reason for reason in reasons))
        self.assertFalse(any("default-VPC placement" in reason for reason in reasons))
        self.assertFalse(any("does not belong" in reason for reason in reasons))

    def test_missing_default_vpc_precondition_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(tmp, "main.tf", NO_DEFAULT_VPC_GUARD)
            reasons = [v.reason for v in check_file(tf)]
        # Only check 2 (the default-VPC precondition) fails.
        self.assertTrue(any("default-VPC placement" in reason for reason in reasons))
        self.assertFalse(any("does not belong" in reason for reason in reasons))
        self.assertFalse(any("must declare" in reason for reason in reasons))

    def test_non_tf_inputs_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "runner.zip"
            artifact.write_bytes(b"\x00\x8a\xff")
            self.assertEqual(check_file(artifact), [])


if __name__ == "__main__":
    unittest.main()
