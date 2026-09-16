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


def _write_named(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
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
                "ELBv2 create actions must require aws:RequestTag/ManagedBy" in reason
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
                          "elasticloadbalancing:DescribeListenerAttributes",
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

            non_contract_violations = [
                violation
                for violation in check_file(tf)
                if "VPN ELBv2 policy contract" not in violation.reason
            ]
            self.assertEqual(non_contract_violations, [])

    def test_missing_vpn_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = []
                  })
                }
                """,
            )
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("VPN ELBv2 policy contract" in reason for reason in reasons), reasons
        )

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
        path = Path("platform/terraform/modules/provisioner-iam/main.tf")

        # Without this assertion, renaming or removing the gwlb policy block
        # would make check_file return [] (resource not found) and this test
        # would pass vacuously, defeating the regression coverage.
        self.assertIn(
            'resource "aws_iam_policy" "gwlb"',
            path.read_text(),
            "provisioner-iam/main.tf must contain aws_iam_policy.gwlb for this check to be meaningful",
        )
        self.assertEqual(check_file(path), [])

    def test_current_policy_requires_listener_attributes_readback(self) -> None:
        source = Path(
            "platform/terraform/modules/provisioner-iam/main.tf"
        ).read_text()
        required = '          "elasticloadbalancing:DescribeListenerAttributes",\n'
        self.assertEqual(source.count(required), 1)
        source = source.replace(required, "")

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), source)
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "ELBv2 describe policy contract is missing required actions" in reason
                and "DescribeListenerAttributes" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_describe_policy_rejects_wildcard_action(self) -> None:
        source = Path(
            "platform/terraform/modules/provisioner-iam/main.tf"
        ).read_text()
        for action in (
            "DescribeLoadBalancers",
            "DescribeLoadBalancerAttributes",
            "DescribeTargetGroups",
            "DescribeTargetGroupAttributes",
            "DescribeTargetHealth",
            "DescribeListeners",
            "DescribeListenerAttributes",
            "DescribeTags",
        ):
            source = source.replace(
                f'          "elasticloadbalancing:{action}",\n', ""
            )
            source = source.replace(
                f'          "elasticloadbalancing:{action}"\n', ""
            )
        marker = "        Action = [\n        ]"
        self.assertIn(marker, source)
        source = source.replace(
            marker,
            '        Action = [\n          "elasticloadbalancing:Describe*"\n        ]',
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), source)
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "ELBv2 describe policy contract contains unapproved actions" in reason
                and "Describe*" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_vpn_create_listener_must_authorize_parent_nlb_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid      = "CreateVpnListener"
                        Action   = ["elasticloadbalancing:CreateListener"]
                        Resource = "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/net/shifter-vpn-*/*/*"
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
            any("parent shifter-vpn NLB" in reason for reason in reasons), reasons
        )

    def test_vpn_create_actions_must_not_mix_resource_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Sid = "CreateVpnResources"
                        Action = [
                          "elasticloadbalancing:CreateLoadBalancer",
                          "elasticloadbalancing:CreateTargetGroup",
                          "elasticloadbalancing:CreateListener"
                        ]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:listener/net/shifter-vpn-*/*/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:targetgroup/shifter-vpn-*/*"
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
                "create actions must use separate statements" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_vpn_resource_allowlist_rejects_required_arn_plus_wildcard(self) -> None:
        source = Path(
            "platform/terraform/modules/provisioner-iam/main.tf"
        ).read_text()
        exact = (
            'Action   = "elasticloadbalancing:CreateLoadBalancer"\n'
            '        Resource = "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*"'
        )
        broadened = (
            'Action = "elasticloadbalancing:CreateLoadBalancer"\n'
            "        Resource = [\n"
            '          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*",\n'
            '          "*"\n'
            "        ]"
        )
        self.assertEqual(source.count(exact), 1)
        source = source.replace(exact, broadened)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), source)
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("exact shifter-vpn namespace" in reason for reason in reasons), reasons
        )

    def test_vpn_action_allowlist_rejects_required_action_plus_wildcard(self) -> None:
        source = Path(
            "platform/terraform/modules/provisioner-iam/main.tf"
        ).read_text()
        exact = 'Action   = "elasticloadbalancing:CreateLoadBalancer"'
        broadened = (
            "Action = [\n"
            '          "elasticloadbalancing:CreateLoadBalancer",\n'
            '          "elasticloadbalancing:*"\n'
            "        ]"
        )
        self.assertEqual(source.count(exact), 1)
        source = source.replace(exact, broadened)

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), source)
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("explicitly approved actions" in reason for reason in reasons), reasons
        )

    def test_vpn_addtags_condition_rejects_required_values_plus_extra(self) -> None:
        source = Path(
            "platform/terraform/modules/provisioner-iam/main.tf"
        ).read_text()
        marker = '"CreateListener"\n            ]'
        marker_at = source.rfind(marker)
        self.assertNotEqual(marker_at, -1)
        source = (
            source[:marker_at]
            + '"CreateListener",\n              "DeleteLoadBalancer"\n            ]'
            + source[marker_at + len(marker) :]
        )

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), source)
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "exact elasticloadbalancing:CreateAction allowlist" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_vpn_create_listener_requires_parent_nlb_resource_tags(self) -> None:
        source = Path(
            "platform/terraform/modules/provisioner-iam/main.tf"
        ).read_text()
        exact = '            "elasticloadbalancing:ResourceTag/ManagedBy"           = "terraform"\n'
        listener_at = source.index('Action   = "elasticloadbalancing:CreateListener"')
        tag_at = source.index(exact, listener_at)
        statement_end = source.index("      },", listener_at)
        self.assertLess(tag_at, statement_end)
        source = source[:tag_at] + source[tag_at + len(exact) :]

        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), source)
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any(
                "CreateListener parent NLB ownership" in reason
                and "ManagedBy" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_vpn_and_gwlb_resources_must_not_share_a_statement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp),
                """
                resource "aws_iam_policy" "gwlb" {
                  policy = jsonencode({
                    Statement = [
                      {
                        Action = ["elasticloadbalancing:CreateLoadBalancer"]
                        Resource = [
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/gwy/*",
                          "arn:aws:elasticloadbalancing:${local.region}:${local.account_id}:loadbalancer/net/shifter-vpn-*/*"
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
            any("must not mix GWLB and VPN" in reason for reason in reasons), reasons
        )

    def test_vpn_listener_requires_creation_time_common_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write_named(
                Path(tmp),
                "vpn.tf",
                """
                resource "aws_lb_listener" "vpn" {
                  load_balancer_arn = aws_lb.vpn[0].arn
                  port              = 1194
                  protocol          = "UDP"
                }
                """,
            )
            reasons = [violation.reason for violation in check_file(tf)]

        self.assertTrue(
            any("local.common_tags" in reason for reason in reasons), reasons
        )

    def test_vpn_listener_with_creation_time_common_tags_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write_named(
                Path(tmp),
                "vpn.tf",
                """
                resource "aws_lb_listener" "vpn" {
                  load_balancer_arn = aws_lb.vpn[0].arn
                  port              = 1194
                  protocol          = "UDP"
                  tags              = local.common_tags
                }
                """,
            )
            self.assertEqual(check_file(tf), [])


class LoadBalancerControllerScopeTest(unittest.TestCase):
    def test_current_controller_policy_passes(self) -> None:
        path = Path("platform/terraform/modules/portal/eks/load_balancer_controller_iam.tf")
        self.assertEqual(check_file(path), [])

    def test_controller_policy_rejects_unscoped_cluster_tag(self) -> None:
        source = Path("platform/terraform/modules/portal/eks/load_balancer_controller_iam.tf").read_text()
        mutated = source.replace(
            '"aws:RequestTag/elbv2.k8s.aws/cluster" = var.cluster_name',
            '"aws:RequestTag/elbv2.k8s.aws/cluster" = "true"',
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_named(Path(tmp), "load_balancer_controller_iam.tf", mutated)
            reasons = [violation.reason for violation in check_file(path)]
        self.assertTrue(any("Load Balancer Controller" in reason for reason in reasons), reasons)

    def test_controller_policy_rejects_waf_mutation_without_exact_acl(self) -> None:
        source = Path("platform/terraform/modules/portal/eks/load_balancer_controller_iam.tf").read_text()
        mutated = source.replace(
            "Resource = aws_wafv2_web_acl.ingress.arn",
            'Resource = "*"',
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_named(Path(tmp), "load_balancer_controller_iam.tf", mutated)
            reasons = [violation.reason for violation in check_file(path)]
        self.assertTrue(any("exact module WAF ACL" in reason for reason in reasons), reasons)

    def test_controller_policy_rejects_security_group_mutation_without_ownership_tag(self) -> None:
        source = Path("platform/terraform/modules/portal/eks/load_balancer_controller_iam.tf").read_text()
        mutated = source.replace(
            '"aws:ResourceTag/elbv2.k8s.aws/cluster" = var.cluster_name',
            '"aws:ResourceTag/elbv2.k8s.aws/cluster" = "unowned"',
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_named(Path(tmp), "load_balancer_controller_iam.tf", mutated)
            reasons = [violation.reason for violation in check_file(path)]
        self.assertTrue(any("security-group mutations" in reason for reason in reasons), reasons)


if __name__ == "__main__":
    unittest.main()
