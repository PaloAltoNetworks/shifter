"""Tests for check_portal_target_sg_sources.py.

Run from the repo root:
    python3 -m unittest scripts.check_portal_target_sg_sources.test_check_portal_target_sg_sources -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_portal_target_sg_sources import check_file


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckPortalTargetSgSourcesTest(unittest.TestCase):
    def test_alb_ingress_cidr_passes(self) -> None:
        # The fixed #933 pattern: the Django target SG admits the ALB-only
        # subnet CIDR contract, which excludes the CTFd public-workload tier.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "ok.tf",
                """
                resource "aws_security_group_rule" "portal_app_from_alb_subnets" {
                  type              = "ingress"
                  from_port         = var.app_port
                  to_port           = var.app_port
                  protocol          = "tcp"
                  cidr_blocks       = module.vpc.alb_ingress_subnet_cidrs
                  security_group_id = module.ec2.security_group_id
                  description       = "HTTP from ALB ingress subnets through inspection"
                }
                """,
            )
            self.assertEqual(check_file(tf), [])

    def test_broad_public_subnet_cidr_rejected(self) -> None:
        # The #911 NET-2 regression: the Django target SG sourced from the
        # whole public tier, where CTFd lives, giving CTFd direct L4 reach.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "regression.tf",
                """
                resource "aws_security_group_rule" "portal_app_from_alb_subnets" {
                  type              = "ingress"
                  from_port         = var.app_port
                  to_port           = var.app_port
                  protocol          = "tcp"
                  cidr_blocks       = module.vpc.public_subnet_cidrs
                  security_group_id = module.ec2.security_group_id
                  description       = "HTTP from ALB public subnets through inspection"
                }
                """,
            )
            violations = check_file(tf)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].source, "module.vpc.public_subnet_cidrs")
        self.assertIn("alb_ingress_subnet_cidrs", violations[0].reason)

    def test_public_workload_cidr_rejected(self) -> None:
        # CTFd's own tier must never be an ingress source for a target SG.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "ctfd_tier.tf",
                """
                resource "aws_security_group_rule" "guacamole_client_from_alb_subnets" {
                  type              = "ingress"
                  from_port         = 8080
                  to_port           = 8080
                  protocol          = "tcp"
                  cidr_blocks       = module.vpc.public_workload_subnet_cidrs
                  security_group_id = module.guacamole.guacamole_client_security_group_id
                  description       = "broken"
                }
                """,
            )
            violations = check_file(tf)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].source, "module.vpc.public_workload_subnet_cidrs")

    def test_literal_broad_cidr_rejected(self) -> None:
        # A hand-written broad literal on a target SG is also rejected.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "literal.tf",
                """
                resource "aws_security_group_rule" "x" {
                  type              = "ingress"
                  from_port         = 8080
                  to_port           = 8080
                  protocol          = "tcp"
                  cidr_blocks       = ["10.0.0.0/16"]
                  security_group_id = module.guacamole.guacamole_client_security_group_id
                }
                """,
            )
            violations = check_file(tf)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].source, "10.0.0.0/16")

    def test_multiline_broad_cidr_rejected(self) -> None:
        # A multiline cidr_blocks list that widens a target SG back to the
        # public tier must still be caught (the parser cannot only look at
        # the `cidr_blocks =` physical line).
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "multiline.tf",
                """
                resource "aws_security_group_rule" "portal_app_from_alb_subnets" {
                  type      = "ingress"
                  from_port = var.app_port
                  to_port   = var.app_port
                  protocol  = "tcp"
                  cidr_blocks = [
                    module.vpc.public_subnet_cidrs,
                  ]
                  security_group_id = module.ec2.security_group_id
                }
                """,
            )
            violations = check_file(tf)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].source, "module.vpc.public_subnet_cidrs")

    def test_multiline_alb_ingress_cidr_passes(self) -> None:
        # The approved source spelled across lines still passes.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "multiline_ok.tf",
                """
                resource "aws_security_group_rule" "portal_app_from_alb_subnets" {
                  type      = "ingress"
                  from_port = var.app_port
                  to_port   = var.app_port
                  protocol  = "tcp"
                  cidr_blocks = [
                    module.vpc.alb_ingress_subnet_cidrs,
                  ]
                  security_group_id = module.ec2.security_group_id
                }
                """,
            )
            self.assertEqual(check_file(tf), [])

    def test_unparseable_cidr_blocks_fails_closed(self) -> None:
        # Defensive fail-closed path: cidr_blocks is present on a target SG
        # ingress but neither the bracket-list nor the bare-ref regex can
        # parse it (here an unclosed bracket). The guard must emit a
        # violation rather than silently pass — a malformed or future
        # syntax must never be treated as "no source".
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "unparseable.tf",
                """
                resource "aws_security_group_rule" "broken" {
                  type      = "ingress"
                  from_port = 8080
                  to_port   = 8080
                  protocol  = "tcp"
                  cidr_blocks = [
                    module.vpc.public_subnet_cidrs
                  security_group_id = module.guacamole.guacamole_client_security_group_id
                }
                """,
            )
            violations = check_file(tf)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].source, "<unparseable cidr_blocks>")

    def test_source_sg_reference_passes(self) -> None:
        # SG-to-SG referencing is the preferred posture and always passes;
        # it is only the inspected (middlebox) path that needs CIDR rules.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "sg_ref.tf",
                """
                resource "aws_security_group_rule" "app_from_alb" {
                  type                     = "ingress"
                  from_port                = var.app_port
                  to_port                  = var.app_port
                  protocol                 = "tcp"
                  source_security_group_id = module.alb.security_group_id
                  security_group_id        = module.ec2.security_group_id
                  description              = "App traffic from ALB"
                }
                """,
            )
            self.assertEqual(check_file(tf), [])

    def test_non_target_sg_ingress_ignored(self) -> None:
        # A broad CIDR on a non-portal-target SG is out of this guard's
        # scope (check_tf_sg_cidrs owns range/provisioner SGs).
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "other.tf",
                """
                resource "aws_security_group_rule" "some_other" {
                  type              = "ingress"
                  from_port         = 443
                  to_port           = 443
                  protocol          = "tcp"
                  cidr_blocks       = module.vpc.public_subnet_cidrs
                  security_group_id = module.redis.security_group_id
                }
                """,
            )
            self.assertEqual(check_file(tf), [])

    def test_egress_on_target_sg_ignored(self) -> None:
        # Egress rules are not a reachability-into-target concern.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                "egress.tf",
                """
                resource "aws_security_group_rule" "egress" {
                  type              = "egress"
                  from_port         = 0
                  to_port           = 0
                  protocol          = "-1"
                  cidr_blocks       = ["0.0.0.0/0"]
                  security_group_id = module.ec2.security_group_id
                }
                """,
            )
            self.assertEqual(check_file(tf), [])

    def test_live_env_roots_pass(self) -> None:
        # The real dev/prod portal env roots must pass after the #933 fix.
        repo_root = Path(__file__).resolve().parents[2]
        roots = [
            repo_root / "platform" / "terraform" / "environments" / env / "portal" / "main.tf"
            for env in ("dev", "prod")
        ]
        present = [p for p in roots if p.exists()]
        if not present:
            self.skipTest("portal env roots not present in this checkout")
        for main_tf in present:
            with self.subTest(main_tf=str(main_tf)):
                self.assertEqual(check_file(main_tf), [], f"{main_tf} should pass")


if __name__ == "__main__":
    unittest.main()
