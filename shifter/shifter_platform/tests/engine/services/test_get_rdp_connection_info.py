"""Tests for get_rdp_connection_info() in engine/services.py."""

import os
from unittest.mock import Mock, patch


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

    def test_gcp_dc_rdp_uses_domain_password_env(self):
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
            patch.dict(os.environ, {"DC_DOMAIN_PASSWORD": "DomainPass123!"}, clear=False),
        ):
            result = get_rdp_connection_info(mock_user, "gdc-dc-uuid-123")

        assert result["rdp_username"] == "Administrator"
        assert result["rdp_password"] == "DomainPass123!"
