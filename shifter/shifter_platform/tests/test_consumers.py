"""Unit tests for WebSocket SSH consumer."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetSSHUsername:
    """Test the get_ssh_username pure function."""

    def test_kali_os_returns_kali_user(self):
        """Kali OS should use 'kali' username."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("kali") == "kali"
        assert get_ssh_username("kali-2023") == "kali"
        assert get_ssh_username("kali-rolling") == "kali"

    def test_windows_os_returns_administrator(self):
        """Windows OS should use 'Administrator' username."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("windows") == "Administrator"
        assert get_ssh_username("windows-server-2022") == "Administrator"
        assert get_ssh_username("windows-10") == "Administrator"

    def test_amazon_linux_returns_ec2_user(self):
        """Amazon Linux should use 'ec2-user' username."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("amazon-linux") == "ec2-user"
        assert get_ssh_username("amazon-linux-2") == "ec2-user"
        assert get_ssh_username("amazon-linux-2023") == "ec2-user"

    def test_ubuntu_returns_ubuntu_user(self):
        """Ubuntu OS should use 'ubuntu' username."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("ubuntu") == "ubuntu"
        assert get_ssh_username("ubuntu-22.04") == "ubuntu"

    def test_debian_returns_ubuntu_user(self):
        """Debian OS should default to 'ubuntu' username."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("debian") == "ubuntu"
        assert get_ssh_username("debian-11") == "ubuntu"

    def test_empty_string_returns_ubuntu(self):
        """Empty OS string should default to 'ubuntu'."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("") == "ubuntu"

    def test_unknown_os_returns_ubuntu(self):
        """Unknown OS should default to 'ubuntu'."""
        from mission_control.consumers import get_ssh_username

        assert get_ssh_username("rhel") == "ubuntu"
        assert get_ssh_username("centos") == "ubuntu"


class TestConnectionDetails:
    """Test the ConnectionDetails dataclass."""

    def test_connection_details_creation(self):
        """ConnectionDetails should store host, secret_arn, and username."""
        from mission_control.consumers import ConnectionDetails

        details = ConnectionDetails(
            host="10.1.1.10",
            secret_arn="arn:aws:secretsmanager:us-east-2:123:secret:key",
            username="kali",
        )

        assert details.host == "10.1.1.10"
        assert details.secret_arn == "arn:aws:secretsmanager:us-east-2:123:secret:key"
        assert details.username == "kali"

    def test_connection_details_equality(self):
        """ConnectionDetails with same values should be equal."""
        from mission_control.consumers import ConnectionDetails

        details1 = ConnectionDetails(host="10.1.1.10", secret_arn="arn:123", username="kali")
        details2 = ConnectionDetails(host="10.1.1.10", secret_arn="arn:123", username="kali")

        assert details1 == details2


class TestSSHConsumerHelperMethods:
    """Test SSHConsumer helper methods for reduced complexity."""

    def test_get_authenticated_user_returns_user(self):
        """_get_authenticated_user should return user from scope."""
        from mission_control.consumers import SSHConsumer

        mock_user = MagicMock()
        mock_user.id = 1

        consumer = SSHConsumer()
        consumer.scope = {"user": mock_user}

        result = consumer._get_authenticated_user()
        assert result == mock_user

    def test_get_authenticated_user_returns_none_for_anonymous(self):
        """_get_authenticated_user should return None for AnonymousUser."""
        from django.contrib.auth.models import AnonymousUser

        from mission_control.consumers import SSHConsumer

        consumer = SSHConsumer()
        consumer.scope = {"user": AnonymousUser()}

        result = consumer._get_authenticated_user()
        assert result is None

    def test_get_authenticated_user_returns_none_for_missing_user(self):
        """_get_authenticated_user should return None when user not in scope."""
        from mission_control.consumers import SSHConsumer

        consumer = SSHConsumer()
        consumer.scope = {}

        result = consumer._get_authenticated_user()
        assert result is None

    def test_resolve_connection_details_kali(self):
        """_resolve_connection_details should return details for kali instance."""
        from mission_control.consumers import ConnectionDetails, SSHConsumer

        mock_range = MagicMock()
        mock_range.attacker_instance = {
            "os": "kali",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        consumer = SSHConsumer()
        consumer.instance_type = "kali"
        consumer.range_id = 1

        result = consumer._resolve_connection_details(mock_range)

        assert result is not None
        assert result == ConnectionDetails(
            host="10.1.1.10",
            secret_arn="arn:aws:secretsmanager:us-east-2:123:secret:key",
            username="kali",
        )

    def test_resolve_connection_details_victim(self):
        """_resolve_connection_details should return details for victim instance."""
        from mission_control.consumers import ConnectionDetails, SSHConsumer

        mock_range = MagicMock()
        mock_range.victim_instances = [
            {
                "os": "ubuntu",
                "private_ip": "10.1.1.20",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            }
        ]

        consumer = SSHConsumer()
        consumer.instance_type = "victim"
        consumer.range_id = 1

        result = consumer._resolve_connection_details(mock_range)

        assert result is not None
        assert result == ConnectionDetails(
            host="10.1.1.20",
            secret_arn="arn:aws:secretsmanager:us-east-2:123:secret:key",
            username="ubuntu",
        )

    def test_resolve_connection_details_missing_instance_returns_none(self):
        """_resolve_connection_details should return None when instance not found."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.attacker_instance = None

        consumer = SSHConsumer()
        consumer.instance_type = "kali"
        consumer.range_id = 1

        result = consumer._resolve_connection_details(mock_range)
        assert result is None

    def test_resolve_connection_details_missing_host_returns_none(self):
        """_resolve_connection_details should return None when host is missing."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.attacker_instance = {
            "os": "kali",
            "private_ip": None,  # Missing host
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        consumer = SSHConsumer()
        consumer.instance_type = "kali"
        consumer.range_id = 1

        result = consumer._resolve_connection_details(mock_range)
        assert result is None

    def test_resolve_connection_details_missing_secret_arn_returns_none(self):
        """_resolve_connection_details should return None when secret_arn is missing."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.attacker_instance = {
            "os": "kali",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": None,  # Missing secret_arn
        }

        consumer = SSHConsumer()
        consumer.instance_type = "kali"
        consumer.range_id = 1

        result = consumer._resolve_connection_details(mock_range)
        assert result is None


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
    async def test_windows_victim_uses_administrator(self):
        """Consumer should use Administrator for Windows instances."""
        from mission_control.consumers import SSHConsumer

        mock_range = MagicMock()
        mock_range.user_id = 1
        mock_range.status = "ready"
        mock_range.victim_instances = [
            {
                "os": "windows",
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
                assert call_kwargs["username"] == "Administrator"

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
