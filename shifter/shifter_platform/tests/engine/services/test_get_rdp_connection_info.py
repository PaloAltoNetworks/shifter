"""Tests for get_rdp_connection_info() in engine/services.py."""

import os
from unittest.mock import Mock, patch

import pytest


class TestGetRdpConnectionInfo:
    """Tests provider-aware RDP connection detail resolution."""

    def test_windows_uses_provider_metadata_secret_reference_for_sftp_key(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-win-uuid-123",
            "role": "victim",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gdc": {
                    "vm_name": "range-42-win-target",
                    "ip": "10.200.0.110",
                    "ssh_secret_ref": "projects/test/secrets/vmrt-ssh-key",
                }
            },
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value="fake-ssh-key-for-testing"),
        ):
            result = get_rdp_connection_info(mock_user, "gdc-win-uuid-123")

        assert result["host"] == "10.200.0.110"
        assert result["private_ip"] == "10.200.0.110"
        assert result["connection_name"] == "range-42-win-target"
        assert result["ssh_key"] == "fake-ssh-key-for-testing"

    def test_gcp_linux_rdp_uses_runtime_password_env(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-ubuntu-uuid-123",
            "role": "victim",
            "os_type": "ubuntu",
            "cloud_provider": "gcp",
            "private_ip": "10.200.0.120",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(os.environ, {"GDC_UBUNTU_PASSWORD": "LabUbuntu123!"}, clear=False),
        ):
            result = get_rdp_connection_info(mock_user, "gdc-ubuntu-uuid-123")

        assert result["rdp_username"] == "ubuntu"
        assert result["rdp_password"] == "LabUbuntu123!"

    def test_gcp_dc_rdp_uses_dc_password_env_on_gcp_portal(self):
        # Same provider as portal deployment: the DC display reads
        # DC_DOMAIN_PASSWORD (which is the same env var the engine
        # provisioner uses to set the DC admin password, so display
        # matches actual).
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-dc-uuid-123",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "private_ip": "10.200.0.130",
            "provider_metadata": {
                "gdc": {
                    "ssh_secret_ref": "projects/test/secrets/vmrt-ssh-key",
                }
            },
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value="fake-ssh-key-for-testing"),
            patch.dict(
                os.environ,
                {"CLOUD_PROVIDER": "gcp", "DC_DOMAIN_PASSWORD": "GcpDcPass123!"},
                clear=False,
            ),
        ):
            result = get_rdp_connection_info(mock_user, "gdc-dc-uuid-123")

        assert result["rdp_username"] == "Administrator"
        assert result["rdp_password"] == "GcpDcPass123!"

    def test_gcp_dc_rdp_does_not_leak_aws_portal_dc_password(self):
        # Cross-provider credential isolation: an AWS-deployed portal
        # (CLOUD_PROVIDER=aws) holds the AWS DC password in
        # DC_DOMAIN_PASSWORD. A GCP DC RDP request to that portal must
        # NOT return that value; the cross-provider path raises a
        # typed ValueError that mission_control surfaces as HTTP 400.
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-dc-uuid-789",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "private_ip": "10.200.0.132",
            "provider_metadata": {
                "gdc": {
                    "ssh_secret_ref": "projects/test/secrets/vmrt-ssh-key",
                }
            },
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        env_aws_portal = {
            "CLOUD_PROVIDER": "aws",
            "DC_DOMAIN_PASSWORD": "AwsLeakProbe123!",
        }
        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value="fake-ssh-key-for-testing"),
            patch.dict(os.environ, env_aws_portal, clear=True),
            pytest.raises(ValueError, match="does not match portal deployment provider"),
        ):
            get_rdp_connection_info(mock_user, "gdc-dc-uuid-789")

    def test_dc_rdp_raises_when_password_env_unset(self):
        # Same-provider request but the secret isn't seeded — the call
        # raises a typed ValueError with a runbook pointer instead of
        # silently returning a passwordless connection payload.
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "aws-dc-uuid-456",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "aws",
            "private_ip": "10.100.0.131",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        env_aws_no_secret = {"CLOUD_PROVIDER": "aws"}
        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(os.environ, env_aws_no_secret, clear=True),
            pytest.raises(ValueError, match="DC_DOMAIN_PASSWORD is not configured"),
        ):
            get_rdp_connection_info(mock_user, "aws-dc-uuid-456")

    def test_aws_dc_rdp_uses_dc_password_env_on_aws_portal(self):
        from engine.models import Range
        from engine.services import get_rdp_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "aws-dc-uuid-123",
            "role": "dc",
            "os_type": "windows",
            "cloud_provider": "aws",
            "private_ip": "10.100.0.130",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        with (
            patch.object(Range, "get_active_for_user", return_value=mock_range),
            patch.dict(
                os.environ,
                {"CLOUD_PROVIDER": "aws", "DC_DOMAIN_PASSWORD": "AwsDcPass123!"},
                clear=False,
            ),
        ):
            result = get_rdp_connection_info(mock_user, "aws-dc-uuid-123")

        assert result["rdp_username"] == "Administrator"
        assert result["rdp_password"] == "AwsDcPass123!"
