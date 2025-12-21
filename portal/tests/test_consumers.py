"""Unit tests for WebSocket SSH consumer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSSHConsumerConnectionDetails:
    """Test that SSH consumer correctly extracts connection details from provisioned_instances."""

    @pytest.mark.asyncio
    async def test_kali_connection_uses_provisioned_instances(self):
        """Consumer should get kali connection details from provisioned_instances, not legacy fields."""
        from mission_control.consumers import SSHConsumer

        # Mock range with provisioned_instances (new format) and empty legacy fields
        mock_range = MagicMock()
        mock_range.user_id = 1
        mock_range.status = "ready"
        mock_range.attacker_instance = {
            "os": "kali",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "instance_id": "i-attacker123",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123456789:secret:attacker-key",
        }
        # Legacy fields are empty - consumer should NOT use these
        mock_range.kali_ip = None
        mock_range.kali_ssh_key_secret_arn = None

        mock_user = MagicMock()
        mock_user.id = 1

        consumer = SSHConsumer()
        consumer.scope = {
            "user": mock_user,
            "url_route": {"kwargs": {"range_id": 1, "instance": "kali"}},
        }
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        with (
            patch("mission_control.consumers.Range") as mock_range_class,
            patch("mission_control.consumers.get_ssh_key", return_value="fake-key"),
            patch("mission_control.consumers.SSHConnection") as mock_ssh,
        ):
            # Mock the async database query
            mock_range_class.Status.READY = "ready"
            mock_get = AsyncMock(return_value=mock_range)
            mock_range_class.objects.select_related.return_value.get = MagicMock()

            with patch("asgiref.sync.sync_to_async", return_value=mock_get):
                mock_ssh_instance = MagicMock()
                mock_ssh_instance.connect = AsyncMock()
                mock_ssh.return_value = mock_ssh_instance

                await consumer._do_connect()

                # Verify SSH was called with data from provisioned_instances
                mock_ssh.assert_called_once()
                call_kwargs = mock_ssh.call_args.kwargs
                assert call_kwargs["host"] == "10.1.1.10"
                assert call_kwargs["username"] == "kali"

    @pytest.mark.asyncio
    async def test_victim_connection_uses_provisioned_instances(self):
        """Consumer should get victim connection details from provisioned_instances, not legacy fields."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.user_id = 1
        mock_range.status = "ready"
        mock_range.victim_instances = [
            {
                "os": "ubuntu",
                "role": "victim",
                "private_ip": "10.1.1.20",
                "instance_id": "i-victim123",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123456789:secret:victim-key",
            }
        ]
        # Legacy fields are empty
        mock_range.victim_ip = None
        mock_range.victim_ssh_key_secret_arn = None

        mock_user = MagicMock()
        mock_user.id = 1

        consumer = SSHConsumer()
        consumer.scope = {
            "user": mock_user,
            "url_route": {"kwargs": {"range_id": 1, "instance": "victim"}},
        }
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        with (
            patch("mission_control.consumers.Range") as mock_range_class,
            patch("mission_control.consumers.get_ssh_key", return_value="fake-key"),
            patch("mission_control.consumers.SSHConnection") as mock_ssh,
        ):
            mock_range_class.Status.READY = "ready"
            mock_get = AsyncMock(return_value=mock_range)

            with patch("asgiref.sync.sync_to_async", return_value=mock_get):
                mock_ssh_instance = MagicMock()
                mock_ssh_instance.connect = AsyncMock()
                mock_ssh.return_value = mock_ssh_instance

                await consumer._do_connect()

                mock_ssh.assert_called_once()
                call_kwargs = mock_ssh.call_args.kwargs
                assert call_kwargs["host"] == "10.1.1.20"
                assert call_kwargs["username"] == "ubuntu"

    @pytest.mark.asyncio
    async def test_amazon_linux_victim_uses_ec2_user(self):
        """Consumer should use ec2-user for Amazon Linux instances."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.user_id = 1
        mock_range.status = "ready"
        mock_range.victim_instances = [
            {
                "os": "amazon-linux-2023",
                "role": "victim",
                "private_ip": "10.1.1.20",
                "instance_id": "i-victim123",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123456789:secret:victim-key",
            }
        ]

        mock_user = MagicMock()
        mock_user.id = 1

        consumer = SSHConsumer()
        consumer.scope = {
            "user": mock_user,
            "url_route": {"kwargs": {"range_id": 1, "instance": "victim"}},
        }
        consumer.close = AsyncMock()
        consumer.accept = AsyncMock()

        with (
            patch("mission_control.consumers.Range") as mock_range_class,
            patch("mission_control.consumers.get_ssh_key", return_value="fake-key"),
            patch("mission_control.consumers.SSHConnection") as mock_ssh,
        ):
            mock_range_class.Status.READY = "ready"
            mock_get = AsyncMock(return_value=mock_range)

            with patch("asgiref.sync.sync_to_async", return_value=mock_get):
                mock_ssh_instance = MagicMock()
                mock_ssh_instance.connect = AsyncMock()
                mock_ssh.return_value = mock_ssh_instance

                await consumer._do_connect()

                mock_ssh.assert_called_once()
                call_kwargs = mock_ssh.call_args.kwargs
                assert call_kwargs["username"] == "ec2-user"

    @pytest.mark.asyncio
    async def test_missing_instance_closes_connection(self):
        """Consumer should close with 4005 if instance not found in provisioned_instances."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.user_id = 1
        mock_range.status = "ready"
        mock_range.attacker_instance = None  # No attacker instance

        mock_user = MagicMock()
        mock_user.id = 1

        consumer = SSHConsumer()
        consumer.scope = {
            "user": mock_user,
            "url_route": {"kwargs": {"range_id": 1, "instance": "kali"}},
        }
        consumer.close = AsyncMock()

        with patch("mission_control.consumers.Range") as mock_range_class:
            mock_range_class.Status.READY = "ready"
            mock_get = AsyncMock(return_value=mock_range)

            with patch("asgiref.sync.sync_to_async", return_value=mock_get):
                await consumer._do_connect()

                consumer.close.assert_called_once_with(code=4005)
