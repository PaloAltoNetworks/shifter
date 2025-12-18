"""Tests for security_groups module."""

import pytest
from unittest.mock import MagicMock, patch

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security_groups import ensure_ssh_from_portal


class TestEnsureSshFromPortal:
    """Tests for ensure_ssh_from_portal function."""

    @patch("shared.security_groups.boto3")
    def test_returns_true_when_rule_already_exists(self, mock_boto3):
        """Should return True without adding rule if it already exists."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        # Simulate existing SSH rule from portal VPC
        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": [
                {
                    "IsEgress": False,
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "CidrIpv4": "10.0.0.0/16",
                }
            ]
        }

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True
        mock_ec2.authorize_security_group_ingress.assert_not_called()

    @patch("shared.security_groups.boto3")
    def test_adds_rule_when_not_exists(self, mock_boto3):
        """Should add SSH rule when it doesn't exist."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        # No existing rules
        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": []
        }

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True
        mock_ec2.authorize_security_group_ingress.assert_called_once_with(
            GroupId="sg-12345",
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [
                        {
                            "CidrIp": "10.0.0.0/16",
                            "Description": "SSH from Portal VPC (browser terminal)",
                        }
                    ],
                }
            ],
        )

    @patch("shared.security_groups.boto3")
    def test_ignores_egress_rules(self, mock_boto3):
        """Should not match egress rules."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        # Egress rule with same parameters should be ignored
        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": [
                {
                    "IsEgress": True,  # Egress, not ingress
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "CidrIpv4": "10.0.0.0/16",
                }
            ]
        }

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True
        # Should add rule since the egress rule doesn't count
        mock_ec2.authorize_security_group_ingress.assert_called_once()

    @patch("shared.security_groups.boto3")
    def test_ignores_different_port(self, mock_boto3):
        """Should not match rules with different ports."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        # Rule for port 443, not 22
        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": [
                {
                    "IsEgress": False,
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "CidrIpv4": "10.0.0.0/16",
                }
            ]
        }

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True
        mock_ec2.authorize_security_group_ingress.assert_called_once()

    @patch("shared.security_groups.boto3")
    def test_ignores_different_cidr(self, mock_boto3):
        """Should not match rules with different CIDR."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        # Rule for different CIDR
        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": [
                {
                    "IsEgress": False,
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "CidrIpv4": "10.1.0.0/16",  # Different CIDR
                }
            ]
        }

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True
        mock_ec2.authorize_security_group_ingress.assert_called_once()

    @patch("shared.security_groups.boto3")
    def test_handles_duplicate_rule_error(self, mock_boto3):
        """Should return True if rule already exists (race condition)."""
        from botocore.exceptions import ClientError

        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": []
        }

        # Simulate race condition - rule added by another process
        mock_ec2.authorize_security_group_ingress.side_effect = ClientError(
            {"Error": {"Code": "InvalidPermission.Duplicate"}},
            "AuthorizeSecurityGroupIngress",
        )

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True

    @patch("shared.security_groups.boto3")
    def test_returns_false_on_other_client_error(self, mock_boto3):
        """Should return False on unexpected ClientError."""
        from botocore.exceptions import ClientError

        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": []
        }

        # Some other error
        mock_ec2.authorize_security_group_ingress.side_effect = ClientError(
            {"Error": {"Code": "UnauthorizedOperation"}},
            "AuthorizeSecurityGroupIngress",
        )

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is False

    @patch("shared.security_groups.boto3")
    def test_returns_false_on_unexpected_exception(self, mock_boto3):
        """Should return False on unexpected exceptions."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        mock_ec2.describe_security_group_rules.side_effect = Exception("Network error")

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is False

    @patch("shared.security_groups.boto3")
    def test_ignores_non_tcp_rules(self, mock_boto3):
        """Should not match non-TCP rules."""
        mock_ec2 = MagicMock()
        mock_boto3.client.return_value = mock_ec2

        # UDP rule, not TCP
        mock_ec2.describe_security_group_rules.return_value = {
            "SecurityGroupRules": [
                {
                    "IsEgress": False,
                    "IpProtocol": "udp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "CidrIpv4": "10.0.0.0/16",
                }
            ]
        }

        result = ensure_ssh_from_portal("sg-12345", "10.0.0.0/16")

        assert result is True
        mock_ec2.authorize_security_group_ingress.assert_called_once()
