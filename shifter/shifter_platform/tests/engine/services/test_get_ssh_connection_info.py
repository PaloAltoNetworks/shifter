"""Tests for get_ssh_connection_info() in engine/services.py."""

from unittest.mock import Mock, patch


class TestGetSSHConnectionInfo:
    """Tests provider-aware SSH connection detail resolution."""

    def test_returns_gcp_connection_info_from_provider_metadata_fallbacks(self):
        from engine.models import Range
        from engine.services import get_ssh_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gcp-instance-uuid-123",
            "role": "attacker",
            "os_type": "kali",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gcp": {
                    "instance_name": "shifter-range-vm-1",
                    "private_ip": "10.50.1.10",
                    "ssh_key_secret_id": "projects/test/secrets/range-ssh-key",
                    "ssh_username": "kali",
                }
            },
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value="fake-ssh-key-for-testing"),
        ):
            result = get_ssh_connection_info(mock_user, "gcp-instance-uuid-123")

        assert result["host"] == "10.50.1.10"
        assert result["private_ip"] == "10.50.1.10"
        assert result["username"] == "kali"
        assert result["connection_name"] == "shifter-range-vm-1"
        assert result["cloud_provider"] == "gcp"

    def test_raises_when_instance_has_no_resolvable_secret_reference(self):
        from engine.models import Range
        from engine.services import get_ssh_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "missing-secret-uuid",
            "role": "victim",
            "os_type": "ubuntu",
            "private_ip": "10.50.1.20",
            "cloud_provider": "gcp",
            "provider_metadata": {"gcp": {"instance_name": "victim-01"}},
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with patch.object(Range.objects, "filter", return_value=mock_queryset):
            try:
                get_ssh_connection_info(mock_user, "missing-secret-uuid")
            except ValueError as exc:
                assert "SSH key" in str(exc)
            else:
                raise AssertionError("Expected ValueError for missing SSH secret reference")

    def test_returns_connection_info_from_gdc_style_provider_metadata(self):
        from engine.models import Range
        from engine.services import get_ssh_connection_info

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "gdc-instance-uuid-123",
            "role": "victim",
            "os_type": "windows",
            "cloud_provider": "gcp",
            "provider_metadata": {
                "gdc": {
                    "vm_name": "range-42-win-target",
                    "ip": "10.200.0.110",
                    "ssh_secret_ref": "projects/test/secrets/vmrt-ssh-key",
                    "username": "Administrator",
                }
            },
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value="fake-ssh-key-for-testing"),
        ):
            result = get_ssh_connection_info(mock_user, "gdc-instance-uuid-123")

        assert result["host"] == "10.200.0.110"
        assert result["private_ip"] == "10.200.0.110"
        assert result["username"] == "Administrator"
        assert result["connection_name"] == "range-42-win-target"
        assert result["cloud_provider"] == "gcp"
