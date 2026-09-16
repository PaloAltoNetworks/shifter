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
                f"""
                resource "aws_iam_role_policy_attachment" "p{n}" {{
                  role       = aws_iam_role.github_actions.name
                  policy_arn = aws_iam_policy.p{n}.arn
                }}
                """
                for n in range(7)
            )
            tf = _write(Path(tmp), "github-oidc.tf", attachments)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("at most" in reason for reason in reasons))

    def test_github_oidc_attachments_within_cap_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attachments = "\n".join(
                f"""
                resource "aws_iam_role_policy_attachment" "p{n}" {{
                  role       = aws_iam_role.github_actions.name
                  policy_arn = aws_iam_policy.p{n}.arn
                }}
                """
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
                              "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole",
                              "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
                              "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
                              "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                              "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
                              "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy",
                              "arn:aws:iam::aws:policy/service-role/AmazonEFSCSIDriverPolicy"
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

    def test_current_eks_deploy_policy_is_scoped(self) -> None:
        path = Path("platform/terraform/global/iam/github-oidc.tf")
        reasons = [
            v.reason for v in check_file(path) if "EKS deploy policy" in v.reason
        ]
        self.assertEqual(reasons, [])

    def test_eks_deploy_policy_rejects_missing_cluster_create(self) -> None:
        source = Path("platform/terraform/global/iam/github-oidc.tf").read_text()
        mutated = source.replace('          "eks:CreateCluster",\n', "", 1)
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "github-oidc.tf", mutated)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("EKS deploy policy" in reason for reason in reasons), reasons
        )


class CheckTfImageRoleTest(unittest.TestCase):
    """Base-image-pipeline role invariants (#1656, ADR-004-R22)."""

    _EXACT_PASSROLE_POLICY = """
        resource "aws_iam_role_policy" "image_pipeline" {
          policy = jsonencode({
            Statement = [{
              Action   = ["iam:PassRole"]
              Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-range-range-instance"
              Condition = {
                StringEquals = {
                  "iam:PassedToService" = "ec2.amazonaws.com"
                }
              }
            }]
          })
        }
    """

    def _oidc(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "github-oidc.tf", body)
            return [v.reason for v in check_file(tf)]

    def test_image_role_exact_subject_and_passrole_pass(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_role" "github_actions_image" {
              assume_role_policy = jsonencode({
                Statement = [{
                  Condition = {
                    StringEquals = {
                      "token.actions.githubusercontent.com:sub" = [
                        "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/dev",
                        "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/main"
                      ]
                    }
                  }
                }]
              })
            }
            """
            + self._EXACT_PASSROLE_POLICY
        )
        self.assertFalse(any("image-pipeline" in reason for reason in reasons))

    def test_image_role_wildcard_subject_rejected(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_role" "github_actions_image" {
              assume_role_policy = jsonencode({
                Statement = [{
                  Condition = {
                    StringEquals = {
                      "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
                    }
                  }
                }]
              })
            }
            """
            + self._EXACT_PASSROLE_POLICY
        )
        self.assertTrue(
            any("not a repo:...:* wildcard" in reason for reason in reasons)
        )

    def test_image_passrole_wildcard_resource_rejected(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_role_policy" "image_pipeline" {
              policy = jsonencode({
                Statement = [{
                  Action   = ["iam:PassRole"]
                  Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*"
                  Condition = {
                    StringEquals = {
                      "iam:PassedToService" = "ec2.amazonaws.com"
                    }
                  }
                }]
              })
            }
            """
        )
        self.assertTrue(any("wildcard resource" in reason for reason in reasons))

    def test_image_passrole_missing_service_condition_rejected(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_role_policy" "image_pipeline" {
              policy = jsonencode({
                Statement = [{
                  Action   = ["iam:PassRole"]
                  Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-range-range-instance"
                }]
              })
            }
            """
        )
        self.assertTrue(any("PassedToService" in reason for reason in reasons))

    def test_deploy_only_oidc_file_skips_image_checks(self) -> None:
        # No github_actions_image role / image_pipeline policy: the new checks
        # must no-op so deploy-only files are unaffected.
        reasons = self._oidc(
            """
            resource "aws_iam_role_policy_attachment" "compute" {
              role       = aws_iam_role.github_actions.name
              policy_arn = aws_iam_policy.compute.arn
            }
            """
        )
        self.assertFalse(any("image-pipeline" in reason for reason in reasons))


class CheckTfVpnGatewayBoundaryTest(unittest.TestCase):
    """VPN gateway permissions-boundary delegation invariants (#1755)."""

    def _oidc(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "github-oidc.tf", body)
            return [
                v.reason for v in check_file(tf) if "VPN gateway boundary" in v.reason
            ]

    def test_boundary_requires_exact_role_and_instance_profile_carveouts(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_policy" "ci_role_permissions_boundary" {
              policy = jsonencode({
                Statement = [{
                  Sid         = "DenyIamEscalation"
                  Effect      = "Deny"
                  Action      = "iam:*"
                  NotResource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
                }]
              })
            }
            """
        )
        self.assertTrue(
            any("instance-profile" in reason for reason in reasons), reasons
        )

    def test_canonical_boundary_resource_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tf = repo_root / "platform/terraform/global/iam/github-oidc.tf"
            tf.parent.mkdir(parents=True)
            tf.write_text('resource "aws_iam_role" "github_actions" {}\n')
            reasons = [v.reason for v in check_file(tf, repo_root=repo_root)]

        self.assertTrue(
            any(
                "ci_role_permissions_boundary" in reason and "required" in reason
                for reason in reasons
            )
        )

    def test_unrelated_fixture_without_boundary_resource_remains_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(
                Path(tmp), "github-oidc.tf", 'resource "aws_iam_role" "fixture" {}\n'
            )
            reasons = [v.reason for v in check_file(tf)]

        self.assertFalse(
            any(
                "ci_role_permissions_boundary" in reason and "required" in reason
                for reason in reasons
            )
        )

    def test_boundary_rejects_broad_vpn_gateway_carveout(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_policy" "ci_role_permissions_boundary" {
              policy = jsonencode({
                Statement = [{
                  Sid    = "DenyIamEscalation"
                  Effect = "Deny"
                  Action = "iam:*"
                  NotResource = [
                    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-polaris-agent",
                    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-vpn-gateway",
                    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway",
                    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*"
                  ]
                }]
              })
            }
            """
        )
        self.assertTrue(
            any("only the exact approved" in reason for reason in reasons), reasons
        )

    def test_boundary_tamper_deny_rejects_approved_actions_plus_extra(self) -> None:
        source = Path("platform/terraform/global/iam/github-oidc.tf").read_text()
        exact = (
            '        Sid    = "DenyVpnGatewayBoundaryTamper"\n'
            '        Effect = "Deny"\n'
            "        Action = [\n"
            '          "iam:PutRolePermissionsBoundary",\n'
            '          "iam:DeleteRolePermissionsBoundary"\n'
            "        ]"
        )
        broadened = exact.replace(
            '          "iam:DeleteRolePermissionsBoundary"\n',
            '          "iam:DeleteRolePermissionsBoundary",\n'
            '          "iam:UpdateAssumeRolePolicy"\n',
        )
        self.assertEqual(source.count(exact), 1)
        source = source.replace(exact, broadened)

        reasons = self._oidc(source)

        self.assertTrue(
            any("only the approved boundary actions" in reason for reason in reasons),
            reasons,
        )

    def test_boundary_requires_vpn_gateway_tamper_deny(self) -> None:
        reasons = self._oidc(
            """
            resource "aws_iam_policy" "ci_role_permissions_boundary" {
              policy = jsonencode({
                Statement = [{
                  Sid    = "DenyIamEscalation"
                  Effect = "Deny"
                  Action = "iam:*"
                  NotResource = [
                    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-${var.environment}-*-vpn-gateway",
                    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway"
                  ]
                }]
              })
            }
            """
        )
        self.assertTrue(any("tamper deny" in reason for reason in reasons), reasons)

    def test_current_boundary_delegation_contract_passes(self) -> None:
        path = Path("platform/terraform/global/iam/github-oidc.tf")
        reasons = [
            v.reason for v in check_file(path) if "VPN gateway boundary" in v.reason
        ]
        self.assertEqual(reasons, [])


class CheckTfVpnGatewayIdentityPolicyTest(unittest.TestCase):
    """Provisioner-side half of VPN gateway IAM delegation (#1755)."""

    def _iam(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "iam.tf", body)
            return [
                v.reason for v in check_file(tf) if "VPN gateway identity" in v.reason
            ]

    def _canonical_mutation(self, exact: str, broadened: str) -> list[str]:
        source = Path("platform/terraform/modules/provisioner-iam/main.tf").read_text()
        self.assertEqual(source.count(exact), 1)
        return self._iam(source.replace(exact, broadened))

    def test_create_role_requires_installation_boundary(self) -> None:
        reasons = self._iam(
            """
            resource "aws_iam_role_policy" "vpn_gateway_role_management" {
              policy = jsonencode({
                Statement = [
                  {
                    Sid      = "CreateVpnGatewayRoleWithBoundary"
                    Action   = "iam:CreateRole"
                    Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
                  }
                ]
              })
            }
            """
        )
        self.assertTrue(
            any("permissions boundary" in reason for reason in reasons), reasons
        )

    def test_canonical_identity_policy_resource_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            tf = repo_root / "platform/terraform/modules/provisioner-iam/main.tf"
            tf.parent.mkdir(parents=True)
            tf.write_text('resource "aws_iam_role" "task" {}\n')
            reasons = [v.reason for v in check_file(tf, repo_root=repo_root)]

        self.assertTrue(
            any(
                "vpn_gateway_role_management" in reason and "required" in reason
                for reason in reasons
            ),
            reasons,
        )

    def test_unrelated_module_without_identity_policy_remains_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "iam.tf", 'resource "aws_iam_role" "fixture" {}\n')
            reasons = [v.reason for v in check_file(tf)]

        self.assertFalse(
            any(
                "vpn_gateway_role_management" in reason and "required" in reason
                for reason in reasons
            )
        )

    def test_managed_policy_and_passrole_must_stay_narrow(self) -> None:
        reasons = self._iam(
            """
            resource "aws_iam_role_policy" "vpn_gateway_role_management" {
              policy = jsonencode({
                Statement = [
                  {
                    Sid      = "UseOnlySsmCorePolicy"
                    Action   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
                    Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
                    Condition = {
                      ArnEquals = {
                        "iam:PolicyARN" = "arn:aws:iam::aws:policy/AdministratorAccess"
                      }
                    }
                  },
                  {
                    Sid      = "PassVpnGatewayRoleOnlyToEc2"
                    Action   = "iam:PassRole"
                    Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
                  }
                ]
              })
            }
            """
        )
        self.assertTrue(
            any("AmazonSSMManagedInstanceCore" in reason for reason in reasons), reasons
        )
        self.assertIn(
            "VPN gateway identity policy PassRole must target the exact role "
            "namespace and require ec2.amazonaws.com",
            reasons,
        )

    def test_create_role_rejects_exact_resource_plus_broad_resource(self) -> None:
        exact = (
            '        Sid      = "CreateVpnGatewayRoleWithBoundary"\n'
            '        Effect   = "Allow"\n'
            '        Action   = "iam:CreateRole"\n'
            '        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"'
        )
        broadened = exact.replace(
            '        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"',
            "        Resource = [\n"
            '          "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway",\n'
            '          "arn:aws:iam::${local.account_id}:role/shifter-*"\n'
            "        ]",
        )

        reasons = self._canonical_mutation(exact, broadened)

        self.assertTrue(any("CreateRole" in reason for reason in reasons), reasons)

    def test_role_management_rejects_approved_actions_plus_extra(self) -> None:
        exact = (
            '          "iam:ListInstanceProfilesForRole",\n'
            '          "iam:ListRoleTags"\n'
            "        ]\n"
            '        Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"'
        )
        broadened = exact.replace(
            '          "iam:ListRoleTags"\n',
            '          "iam:ListRoleTags",\n          "iam:UpdateAssumeRolePolicy"\n',
        )

        reasons = self._canonical_mutation(exact, broadened)

        self.assertTrue(
            any("role management must contain only" in reason for reason in reasons),
            reasons,
        )

    def test_managed_policy_rejects_ssm_core_plus_extra_policy(self) -> None:
        exact = '            "iam:PolicyARN" = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"'
        broadened = (
            '            "iam:PolicyARN" = [\n'
            '              "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",\n'
            '              "arn:aws:iam::aws:policy/AdministratorAccess"\n'
            "            ]"
        )

        reasons = self._canonical_mutation(exact, broadened)

        self.assertTrue(
            any("AmazonSSMManagedInstanceCore" in reason for reason in reasons), reasons
        )

    def test_instance_profile_rejects_exact_resource_plus_wildcard(self) -> None:
        exact = '        Resource = "arn:aws:iam::${local.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway"'
        broadened = (
            "        Resource = [\n"
            '          "arn:aws:iam::${local.account_id}:instance-profile/shifter-${var.environment}-*-vpn-gateway",\n'
            '          "*"\n'
            "        ]"
        )

        reasons = self._canonical_mutation(exact, broadened)

        self.assertTrue(
            any("exact instance-profile namespace" in reason for reason in reasons),
            reasons,
        )

    def test_passrole_rejects_ec2_plus_additional_service(self) -> None:
        exact = '            "iam:PassedToService" = "ec2.amazonaws.com"'
        broadened = (
            '            "iam:PassedToService" = [\n'
            '              "ec2.amazonaws.com",\n'
            '              "lambda.amazonaws.com"\n'
            "            ]"
        )

        reasons = self._canonical_mutation(exact, broadened)

        self.assertIn(
            "VPN gateway identity policy PassRole must target the exact role "
            "namespace and require ec2.amazonaws.com",
            reasons,
        )

    def test_identity_policy_must_not_mutate_permissions_boundary(self) -> None:
        reasons = self._iam(
            """
            resource "aws_iam_role_policy" "vpn_gateway_role_management" {
              policy = jsonencode({
                Statement = [
                  {
                    Sid      = "ManageVpnGatewayRole"
                    Action   = ["iam:PutRolePermissionsBoundary"]
                    Resource = "arn:aws:iam::${local.account_id}:role/shifter-${var.environment}-*-vpn-gateway"
                  }
                ]
              })
            }
            """
        )
        self.assertTrue(any("must not mutate" in reason for reason in reasons), reasons)

    def test_current_vpn_gateway_identity_policy_passes(self) -> None:
        path = Path("platform/terraform/modules/provisioner-iam/main.tf")
        self.assertIn(
            'resource "aws_iam_role_policy" "vpn_gateway_role_management"',
            path.read_text(),
        )
        reasons = [
            v.reason for v in check_file(path) if "VPN gateway identity" in v.reason
        ]
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
