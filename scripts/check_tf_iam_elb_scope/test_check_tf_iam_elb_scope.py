"""Tests for check_tf_iam_elb_scope.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_iam_elb_scope.test_check_tf_iam_elb_scope -v
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_iam_elb_scope import check_file


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "iam.tf"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfIamElbScopeTest(unittest.TestCase):
    def test_wildcard_mutation_statement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "elasticloadbalancing:CreateLoadBalancer",
                          "elasticloadbalancing:DeleteLoadBalancer",
                          "elasticloadbalancing:ModifyTargetGroupAttributes",
                          "elasticloadbalancing:Describe*"
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
            any("must not use Resource=*" in reason for reason in reasons),
            reasons,
        )
        self.assertTrue(
            any("must be scoped to GWLB ELBv2 ARNs" in reason for reason in reasons),
            reasons,
        )
        self.assertTrue(
            any(
                "elasticloadbalancing:ResourceTag/shifter:system" in reason
                for reason in reasons
            ),
            reasons,
        )
        self.assertTrue(
            any("Describe APIs must stay separate" in reason for reason in reasons),
            reasons,
        )

    def test_wildcard_action_pattern_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = [
                          "elasticloadbalancing:*"
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
            any("wildcard action patterns" in reason for reason in reasons),
            reasons,
        )
        self.assertTrue(
            any("must not use Resource=*" in reason for reason in reasons),
            reasons,
        )

    def test_create_statement_missing_request_tags_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "GWLBCreate"
                        Action = [
                          "elasticloadbalancing:CreateLoadBalancer",
                          "elasticloadbalancing:CreateTargetGroup",
                          "elasticloadbalancing:CreateListener"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
                        ]
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "ELBv2 create actions must require aws:RequestTag/shifter:system"
                in reason
                for reason in reasons
            ),
            reasons,
        )
        self.assertTrue(
            any(
                "ELBv2 create actions must require aws:RequestTag/ManagedBy"
                in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_create_statement_on_wildcard_resource_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "GWLBCreateWildcard"
                        Action = [
                          "elasticloadbalancing:CreateLoadBalancer",
                          "elasticloadbalancing:CreateTargetGroup",
                          "elasticloadbalancing:CreateListener"
                        ]
                        Resource = "*"
                        Condition = {
                          StringEquals = {
                            "aws:RequestTag/shifter:system"      = "shifter"
                            "aws:RequestTag/shifter:environment" = var.environment
                            "aws:RequestTag/ManagedBy"           = "terraform"
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("must not use Resource=*" in reason for reason in reasons),
            reasons,
        )

    def test_addtags_missing_create_action_condition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "GWLBTagOnCreate"
                        Action = [
                          "elasticloadbalancing:AddTags"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "aws:RequestTag/shifter:system"      = "shifter"
                            "aws:RequestTag/shifter:environment" = var.environment
                            "aws:RequestTag/ManagedBy"           = "terraform"
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "AddTags must require elasticloadbalancing:CreateAction" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_addtags_missing_request_tag_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "GWLBTagOnCreateMissingTag"
                        Action = [
                          "elasticloadbalancing:AddTags"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "elasticloadbalancing:CreateAction" = [
                              "CreateLoadBalancer"
                            ]
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "AddTags must require aws:RequestTag/shifter:system" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_scoped_statements_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "GWLBDescribe"
                        Action = [
                          "elasticloadbalancing:DescribeLoadBalancers",
                          "elasticloadbalancing:DescribeLoadBalancerAttributes",
                          "elasticloadbalancing:DescribeTargetGroups",
                          "elasticloadbalancing:DescribeTargetGroupAttributes",
                          "elasticloadbalancing:DescribeTargetHealth",
                          "elasticloadbalancing:DescribeListeners",
                          "elasticloadbalancing:DescribeTags"
                        ]
                        Resource = "*"
                      },
                      {
                        Sid = "GWLBCreate"
                        Action = [
                          "elasticloadbalancing:CreateLoadBalancer",
                          "elasticloadbalancing:CreateTargetGroup",
                          "elasticloadbalancing:CreateListener"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "aws:RequestTag/shifter:system"      = "shifter"
                            "aws:RequestTag/shifter:environment" = var.environment
                            "aws:RequestTag/ManagedBy"           = "terraform"
                          }
                        }
                      },
                      {
                        Sid = "GWLBMutateOwned"
                        Action = [
                          "elasticloadbalancing:DeleteLoadBalancer",
                          "elasticloadbalancing:DeleteTargetGroup",
                          "elasticloadbalancing:DeleteListener",
                          "elasticloadbalancing:RegisterTargets",
                          "elasticloadbalancing:DeregisterTargets",
                          "elasticloadbalancing:ModifyLoadBalancerAttributes",
                          "elasticloadbalancing:ModifyTargetGroup",
                          "elasticloadbalancing:ModifyTargetGroupAttributes",
                          "elasticloadbalancing:RemoveTags"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "elasticloadbalancing:ResourceTag/shifter:system"      = "shifter"
                            "elasticloadbalancing:ResourceTag/shifter:environment" = var.environment
                            "elasticloadbalancing:ResourceTag/ManagedBy"           = "terraform"
                          }
                        }
                      },
                      {
                        Sid = "GWLBTagOnCreate"
                        Action = [
                          "elasticloadbalancing:AddTags"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/gwy/*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "elasticloadbalancing:CreateAction" = [
                              "CreateLoadBalancer",
                              "CreateTargetGroup",
                              "CreateListener"
                            ]
                            "aws:RequestTag/shifter:system"      = "shifter"
                            "aws:RequestTag/shifter:environment" = var.environment
                            "aws:RequestTag/ManagedBy"           = "terraform"
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )

            self.assertEqual(check_file(tf), [])

    def test_missing_gwy_resource_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_role_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "ELBMutateButWrongResourceType"
                        Action = [
                          "elasticloadbalancing:DeleteLoadBalancer",
                          "elasticloadbalancing:ModifyTargetGroupAttributes"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/app/*"
                        ]
                        Condition = {
                          StringEquals = {
                            "elasticloadbalancing:ResourceTag/shifter:system"      = "shifter"
                            "elasticloadbalancing:ResourceTag/shifter:environment" = var.environment
                            "elasticloadbalancing:ResourceTag/ManagedBy"           = "terraform"
                          }
                        }
                      }
                    ]
                  })
                }
                """,
            )

            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("must be scoped to GWLB ELBv2 ARNs" in reason for reason in reasons),
            reasons,
        )

    def test_current_engine_provisioner_policy_scopes_mutable_elb_actions(self) -> None:
        path = Path("platform/terraform/modules/engine-provisioner/iam.tf")

        # Without this assertion, renaming or removing the gwlb policy block
        # would make check_file return [] (resource not found) and this test
        # would pass vacuously, defeating the regression coverage.
        self.assertIn(
            'resource "aws_iam_role_policy" "gwlb"',
            path.read_text(),
            "iam.tf must contain aws_iam_role_policy.gwlb for this check to be meaningful",
        )
        self.assertEqual(check_file(path), [])


if __name__ == "__main__":
    unittest.main()
