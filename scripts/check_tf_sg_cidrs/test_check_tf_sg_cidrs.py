"""Tests for check_tf_sg_cidrs.py.

Run from the repo root:
    python3 -m pytest scripts/check_tf_sg_cidrs/test_check_tf_sg_cidrs.py -v
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from check_tf_sg_cidrs import check_file


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_polaris_legacy_shared_sg_with_vpc_wide_cidr(tmp_path: Path) -> None:
    """The 3.93.x shared SG that produced the cross-range leak.

    `cidr_blocks = ["10.1.0.0/16"]` on an inline ingress block of an
    `aws_security_group` resource must be rejected — that's the exact
    pattern that let polaris range 1's kali reach range 0's DC.
    """
    tf = _write(
        tmp_path,
        "broken.tf",
        """
        resource "aws_security_group" "polaris" {
          name   = "polaris-bake-sg"
          vpc_id = var.range_vpc_id

          ingress {
            description = "All intra-range-VPC traffic"
            from_port   = 0
            to_port     = 0
            protocol    = "-1"
            cidr_blocks = ["10.1.0.0/16"]
          }
        }
        """,
    )
    violations = check_file(tf)
    assert len(violations) == 1
    assert violations[0].cidr == "10.1.0.0/16"
    assert "broader than /24" in violations[0].reason


def test_per_range_each_value_cidr_passes(tmp_path: Path) -> None:
    """The fixed polaris pattern: per-range SG with `each.value.cidr`."""
    tf = _write(
        tmp_path,
        "fixed.tf",
        """
        resource "aws_security_group" "polaris" {
          for_each = local.range_subnets
          name     = "polaris-bake-sg-${each.key}"
          vpc_id   = var.range_vpc_id

          ingress {
            description = "Intra-range /28 traffic"
            from_port   = 0
            to_port     = 0
            protocol    = "-1"
            cidr_blocks = [each.value.cidr]
          }

          ingress {
            description = "SSH from portal VPC"
            from_port   = 22
            to_port     = 22
            protocol    = "tcp"
            cidr_blocks = [var.portal_vpc_cidr]
          }
        }
        """,
    )
    assert check_file(tf) == []


def test_egress_zero_route_is_ignored(tmp_path: Path) -> None:
    """Egress 0.0.0.0/0 is the standard NAT pattern — allowed."""
    tf = _write(
        tmp_path,
        "egress.tf",
        """
        resource "aws_security_group" "polaris" {
          name   = "x"
          vpc_id = var.range_vpc_id

          egress {
            from_port   = 0
            to_port     = 0
            protocol    = "-1"
            cidr_blocks = ["0.0.0.0/0"]
          }
        }
        """,
    )
    assert check_file(tf) == []


def test_ingress_zero_route_is_rejected(tmp_path: Path) -> None:
    """Ingress 0.0.0.0/0 must be rejected."""
    tf = _write(
        tmp_path,
        "open_ingress.tf",
        """
        resource "aws_security_group" "polaris" {
          name   = "x"
          vpc_id = var.range_vpc_id

          ingress {
            from_port   = 22
            to_port     = 22
            protocol    = "tcp"
            cidr_blocks = ["0.0.0.0/0"]
          }
        }
        """,
    )
    violations = check_file(tf)
    assert len(violations) == 1
    assert violations[0].cidr == "0.0.0.0/0"
    assert "0.0.0.0/0 is forbidden" in violations[0].reason


@pytest.mark.parametrize(
    "cidr",
    ["10.0.0.0/8", "10.1.0.0/16", "172.16.0.0/12", "192.168.0.0/16"],
)
def test_broad_rfc1918_literals_are_rejected(
    tmp_path: Path, cidr: str
) -> None:
    """Any literal CIDR broader than /24 in ingress is rejected."""
    tf = _write(
        tmp_path,
        "broad.tf",
        f"""
        resource "aws_security_group" "polaris" {{
          name   = "x"
          vpc_id = var.range_vpc_id

          ingress {{
            from_port   = 0
            to_port     = 0
            protocol    = "-1"
            cidr_blocks = ["{cidr}"]
          }}
        }}
        """,
    )
    violations = check_file(tf)
    assert len(violations) == 1
    assert violations[0].cidr == cidr


def test_narrow_literal_passes(tmp_path: Path) -> None:
    """A /24 or narrower literal is allowed."""
    tf = _write(
        tmp_path,
        "narrow.tf",
        """
        resource "aws_security_group" "polaris" {
          name   = "x"
          vpc_id = var.range_vpc_id

          ingress {
            from_port   = 0
            to_port     = 0
            protocol    = "-1"
            cidr_blocks = ["10.1.100.0/28"]
          }
        }
        """,
    )
    assert check_file(tf) == []


def test_unknown_var_is_rejected(tmp_path: Path) -> None:
    """`var.X` references must be on the allowlist."""
    tf = _write(
        tmp_path,
        "unknown_var.tf",
        """
        resource "aws_security_group" "polaris" {
          name   = "x"
          vpc_id = var.range_vpc_id

          ingress {
            from_port   = 0
            to_port     = 0
            protocol    = "-1"
            cidr_blocks = [var.some_other_cidr]
          }
        }
        """,
    )
    violations = check_file(tf)
    assert len(violations) == 1
    assert "unknown variable reference" in violations[0].reason


def test_aws_security_group_rule_ingress_with_broad_cidr_is_rejected(
    tmp_path: Path,
) -> None:
    """Top-level aws_security_group_rule ingress must also be checked.

    The provisioner uses `aws_security_group_rule` for connected-subnet
    ingress; same lint applies.
    """
    tf = _write(
        tmp_path,
        "rule.tf",
        """
        resource "aws_security_group_rule" "wide_open" {
          type              = "ingress"
          security_group_id = aws_security_group.subnet["a"].id
          protocol          = "-1"
          from_port         = 0
          to_port           = 0
          cidr_blocks       = ["10.0.0.0/8"]
        }
        """,
    )
    violations = check_file(tf)
    assert len(violations) == 1
    assert violations[0].cidr == "10.0.0.0/8"


def test_aws_security_group_rule_egress_is_ignored(
    tmp_path: Path,
) -> None:
    """Egress aws_security_group_rule is not checked."""
    tf = _write(
        tmp_path,
        "egress_rule.tf",
        """
        resource "aws_security_group_rule" "egress_all" {
          type              = "egress"
          security_group_id = aws_security_group.subnet["a"].id
          protocol          = "-1"
          from_port         = 0
          to_port           = 0
          cidr_blocks       = ["0.0.0.0/0"]
        }
        """,
    )
    assert check_file(tf) == []


def test_provisioner_module_passes(tmp_path: Path) -> None:
    """The shifter provisioner range module must pass — it's the
    pattern we copied from."""
    repo_root = Path(__file__).resolve().parents[2]
    main_tf = (
        repo_root
        / "shifter"
        / "engine"
        / "provisioner"
        / "terraform"
        / "modules"
        / "range"
        / "main.tf"
    )
    if not main_tf.exists():
        pytest.skip(f"{main_tf} not present in this checkout")
    assert check_file(main_tf) == []


def test_polaris_module_passes(tmp_path: Path) -> None:
    """The polaris range module after the per-range SG fix must pass."""
    repo_root = Path(__file__).resolve().parents[2]
    polaris_dir = repo_root / "scripts" / "polaris-aws-range"
    for tf in polaris_dir.glob("*.tf"):
        assert check_file(tf) == [], f"{tf} should pass but didn't"
