"""Configuration tests for Pulumi provisioner.

Tests config loading from Pulumi config and database.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig, generate_presigned_url, get_range_from_db


class TestGeneratePresignedUrl:
    """Tests for S3 presigned URL generation."""

    def test_generate_presigned_url_success(self, mock_boto3_clients):
        """Valid S3 presigned URL should be returned."""
        url = generate_presigned_url("test-bucket", "agents/installer.sh")
        assert url == "https://s3.example.com/presigned-url"

    def test_generate_presigned_url_custom_expiry(self, mock_boto3_clients):
        """Custom expires_in value should be used."""
        url = generate_presigned_url("test-bucket", "key", expires_in=7200)

        # Verify the S3 client was called with custom expiry
        mock_boto3_clients["s3"].generate_presigned_url.assert_called_once()
        call_kwargs = mock_boto3_clients["s3"].generate_presigned_url.call_args
        assert call_kwargs[1]["ExpiresIn"] == 7200

    def test_generate_presigned_url_default_expiry(self, mock_boto3_clients):
        """Default expiry should be 3600 seconds."""
        url = generate_presigned_url("test-bucket", "key")

        call_kwargs = mock_boto3_clients["s3"].generate_presigned_url.call_args
        assert call_kwargs[1]["ExpiresIn"] == 3600

    def test_generate_presigned_url_params(self, mock_boto3_clients):
        """Correct parameters should be passed to S3 client."""
        url = generate_presigned_url("my-bucket", "path/to/file.tar.gz")

        mock_boto3_clients["s3"].generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/file.tar.gz"},
            ExpiresIn=3600,
        )


class TestGetRangeFromDb:
    """Tests for database range loading."""

    def test_get_range_from_db_success(self, mock_boto3_clients, mock_env_vars_minimal):
        """Range data should be loaded with agent join."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                42,  # id
                1,  # user_id
                5,  # subnet_index
                1,  # agent_id
                None,  # instance_config
                "agents/xdr.tar.gz",  # agent_s3_key
                "linux-debian",  # agent_os_slug
            )
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["id"] == 42
            assert result["user_id"] == 1
            assert result["subnet_index"] == 5
            assert result["agent_id"] == 1
            assert result["agent_s3_key"] == "agents/xdr.tar.gz"
            assert result["agent_os_slug"] == "linux-debian"

    def test_get_range_from_db_returns_agent_os_slug(self, mock_boto3_clients, mock_env_vars_minimal):
        """Range data should include agent's OS slug from OperatingSystem table."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                42,  # id
                1,  # user_id
                5,  # subnet_index
                1,  # agent_id
                None,  # instance_config
                "agents/xdr.msi",  # agent_s3_key
                "windows",  # agent_os_slug - from OperatingSystem.slug
            )
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["agent_os_slug"] == "windows"

    def test_get_range_from_db_not_found(self, mock_boto3_clients, mock_env_vars_minimal):
        """ValueError should be raised for missing range."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None  # No row found
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            with pytest.raises(ValueError, match="Range 999 not found"):
                get_range_from_db(999)

    def test_get_range_from_db_null_agent(self, mock_boto3_clients, mock_env_vars_minimal):
        """Range without agent_id should return nulls for agent fields."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                43,  # id
                2,  # user_id
                6,  # subnet_index
                None,  # agent_id (no agent)
                None,  # instance_config
                None,  # agent_s3_key (no agent)
                None,  # agent_os_slug (no agent)
            )
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(43)

            assert result["id"] == 43
            assert result["agent_id"] is None
            assert result["agent_s3_key"] is None
            assert result["agent_os_slug"] is None

    def test_get_range_from_db_custom_instance_config(self, mock_boto3_clients, mock_env_vars_minimal):
        """Range with custom instance_config should return it."""
        custom_config = [
            {"role": "attacker", "os": "kali", "instance_type": "t3.medium"},
            {"role": "victim", "os": "ubuntu", "instance_type": "t3.small"},
        ]

        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                44,  # id
                3,  # user_id
                7,  # subnet_index
                None,  # agent_id
                custom_config,  # instance_config
                None,  # agent_s3_key
                None,  # agent_os_slug
            )
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(44)

            assert result["instance_config"] == custom_config


class TestInstanceConfigDataclass:
    """Tests for the InstanceConfig dataclass."""

    def test_instance_config_defaults(self):
        """Default values for optional fields."""
        config = InstanceConfig(
            role="victim",
            os_type="ubuntu",
            instance_type="t3.micro",
        )
        assert config.role == "victim"
        assert config.os_type == "ubuntu"
        assert config.instance_type == "t3.micro"
        assert config.agent_id is None
        assert config.agent_s3_key is None
        assert config.agent_presigned_url is None

    def test_instance_config_all_fields(self):
        """All fields should be populated."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
            agent_id=42,
            agent_s3_key="agents/xdr.msi",
            agent_presigned_url="https://s3.example.com/signed",
        )
        assert config.role == "victim"
        assert config.os_type == "windows"
        assert config.instance_type == "t3.medium"
        assert config.agent_id == 42
        assert config.agent_s3_key == "agents/xdr.msi"
        assert config.agent_presigned_url == "https://s3.example.com/signed"

    def test_instance_config_attacker(self):
        """Attacker config should not have agent fields."""
        config = InstanceConfig(
            role="attacker",
            os_type="kali",
            instance_type="t3.small",
        )
        assert config.role == "attacker"
        assert config.agent_id is None
        assert config.agent_s3_key is None


class TestRangeConfigDataclass:
    """Tests for the RangeConfig dataclass."""

    def test_range_config_required_fields(self):
        """All required fields should be present."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
            ],
            vpc_id="vpc-123",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-123",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-victim",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )

        assert config.range_id == 42
        assert config.user_id == 1
        assert config.subnet_index == 5
        assert config.environment == "dev"
        assert len(config.instances) == 1
        assert config.vpc_id == "vpc-123"
        assert config.vpc_cidr == "10.1.0.0/16"
        assert config.route_table_id == "rtb-123"
        assert config.kali_security_group_id == "sg-kali"
        assert config.victim_security_group_id == "sg-victim"
        assert config.instance_profile_name == "profile"
        assert config.kali_ami_id == "ami-kali"
        assert config.victim_ami_id == "ami-victim"
        assert config.windows_ami_id == "ami-windows"
        assert config.agent_s3_bucket == "bucket"
        assert config.availability_zone == "us-east-2a"

    def test_range_config_optional_defaults(self):
        """portal_vpc_cidr should default to empty string."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],
            vpc_id="vpc-123",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-123",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-victim",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )

        assert config.portal_vpc_cidr == ""

    def test_range_config_with_portal_vpc_cidr(self):
        """portal_vpc_cidr can be set."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],
            vpc_id="vpc-123",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-123",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-victim",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
            portal_vpc_cidr="10.0.0.0/16",
        )

        assert config.portal_vpc_cidr == "10.0.0.0/16"


class TestLoadConfigIntegration:
    """Integration tests for load_config function.

    These tests actually call load_config() with mocked dependencies.
    Uses mock_pulumi_config fixture from conftest.py.
    """

    @pytest.fixture
    def mock_db_range_data(self, mocker):
        """Mock get_range_from_db to return test data."""
        def _mock_db(range_id, instance_config=None, agent_id=None, agent_s3_key=None, agent_os_slug=None):
            mock_data = {
                "id": range_id,
                "user_id": 1,
                "subnet_index": 5,
                "agent_id": agent_id,
                "instance_config": instance_config,
                "agent_s3_key": agent_s3_key,
                "agent_os_slug": agent_os_slug,
            }
            mocker.patch("config.get_range_from_db", return_value=mock_data)
            return mock_data
        return _mock_db

    def test_load_config_returns_range_config(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """load_config should return a RangeConfig with all fields populated."""
        from config import load_config

        mock_db_range_data(42)

        result = load_config()

        assert isinstance(result, RangeConfig)
        assert result.range_id == 42
        assert result.user_id == 1
        assert result.subnet_index == 5
        assert result.environment == "dev"
        assert result.vpc_id == "vpc-test123"
        assert result.vpc_cidr == "10.1.0.0/16"
        assert result.route_table_id == "rtb-test123"
        assert result.kali_security_group_id == "sg-kali-test"
        assert result.victim_security_group_id == "sg-victim-test"
        assert result.kali_ami_id == "ami-kali-test"
        assert result.victim_ami_id == "ami-victim-test"
        assert result.windows_ami_id == "ami-windows-test"
        assert result.availability_zone == "us-east-2a"
        assert result.agent_s3_bucket == "test-agents-bucket"

    def test_load_config_default_instances_when_no_config(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """When no instance_config, default should be 1 Kali + 1 Victim."""
        from config import load_config

        # No custom instance_config in DB
        mock_db_range_data(42, instance_config=None, agent_id=1, agent_s3_key="agents/xdr.tar.gz")

        result = load_config()

        assert len(result.instances) == 2
        assert result.instances[0].role == "attacker"
        assert result.instances[0].os_type == "kali"
        # Instance types come from env vars (set by autouse fixture)
        assert result.instances[0].instance_type == os.environ["KALI_INSTANCE_TYPE"]
        assert result.instances[1].role == "victim"
        assert result.instances[1].os_type == "ubuntu"
        assert result.instances[1].instance_type == os.environ["VICTIM_INSTANCE_TYPE"]
        assert result.instances[1].agent_id == 1
        assert result.instances[1].agent_s3_key == "agents/xdr.tar.gz"

    def test_load_config_custom_instance_config(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """Custom instance_config from DB should be parsed into InstanceConfig objects."""
        from config import load_config

        custom_config = [
            {"role": "attacker", "os": "kali", "instance_type": "t3.medium"},
            {"role": "victim", "os": "windows", "instance_type": "t3.large",
             "agent_id": 2, "agent_s3_key": "agents/xdr.msi"},
        ]
        mock_db_range_data(42, instance_config=custom_config)

        result = load_config()

        assert len(result.instances) == 2
        assert result.instances[0].role == "attacker"
        assert result.instances[0].os_type == "kali"
        assert result.instances[0].instance_type == "t3.medium"
        assert result.instances[1].role == "victim"
        assert result.instances[1].os_type == "windows"
        assert result.instances[1].instance_type == "t3.large"
        assert result.instances[1].agent_id == 2
        assert result.instances[1].agent_s3_key == "agents/xdr.msi"

    def test_load_config_generates_presigned_url(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """Presigned URL should be generated for agents with s3_key."""
        from config import load_config

        mock_db_range_data(42, agent_id=1, agent_s3_key="agents/xdr.tar.gz")

        result = load_config()

        # Victim instance should have presigned URL
        victim = result.instances[1]
        assert victim.agent_presigned_url == "https://s3.example.com/presigned-url"

        # Verify S3 client was called
        mock_boto3_clients["s3"].generate_presigned_url.assert_called()

    def test_load_config_no_presigned_url_without_agent(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """No presigned URL when no agent_s3_key."""
        from config import load_config

        mock_db_range_data(42, agent_id=None, agent_s3_key=None)

        result = load_config()

        # Victim instance should NOT have presigned URL
        victim = result.instances[1]
        assert victim.agent_presigned_url is None

    def test_load_config_empty_optional_configs(self, mocker, mock_boto3_clients):
        """Optional config values should default to empty string."""
        from config import load_config

        mock_config = MagicMock()
        mock_config.require.side_effect = lambda key: {
            "environment": "prod",
            "rangeVpcId": "vpc-123",
            "rangeVpcCidr": "10.1.0.0/16",
            "rangeRouteTableId": "rtb-123",
            "kaliSecurityGroupId": "sg-kali",
            "victimSecurityGroupId": "sg-victim",
            "kaliAmiId": "ami-kali",
            "victimAmiId": "ami-victim",
            "availabilityZone": "us-east-2a",
        }.get(key, "")
        mock_config.require_int.return_value = 42
        mock_config.get.return_value = None  # All optional configs return None

        mocker.patch("pulumi.Config", return_value=mock_config)
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": None, "agent_s3_key": None,
        })

        result = load_config()

        # Optional fields should be empty strings
        assert result.windows_ami_id == ""
        assert result.instance_profile_name == ""
        assert result.agent_s3_bucket == ""
        assert result.portal_vpc_cidr == ""

    def test_load_config_calls_get_range_from_db(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should call get_range_from_db with correct range_id."""
        from config import load_config

        mock_get_range = mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": None, "agent_s3_key": None,
        })

        load_config()

        mock_get_range.assert_called_once_with(42)

    def test_load_config_uses_pulumi_config_require(
        self, mock_db_range_data, mocker, mock_boto3_clients
    ):
        """load_config should use pulumi.Config().require for mandatory values."""
        from config import load_config

        mock_config = MagicMock()
        mock_config.require.side_effect = lambda key: f"value-{key}"
        mock_config.require_int.return_value = 42
        mock_config.get.return_value = None

        mocker.patch("pulumi.Config", return_value=mock_config)
        mock_db_range_data(42)

        load_config()

        # Verify require was called for mandatory fields
        require_calls = [call[0][0] for call in mock_config.require.call_args_list]
        assert "environment" in require_calls
        assert "rangeVpcId" in require_calls
        assert "rangeVpcCidr" in require_calls
        assert "kaliSecurityGroupId" in require_calls
        assert "victimSecurityGroupId" in require_calls
        assert "kaliAmiId" in require_calls
        assert "victimAmiId" in require_calls
        assert "availabilityZone" in require_calls


class TestAgentOsToVictimOsMapping:
    """Tests for agent OS slug → victim os_type mapping.

    When a user uploads a Windows agent (.msi), the victim instance should
    be Windows. When they upload a Linux agent (.deb, .rpm), the victim
    should be Ubuntu (Linux).

    Uses mock_pulumi_config fixture from conftest.py.
    """

    def test_windows_agent_creates_windows_victim(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """When agent OS is 'windows', victim os_type should be 'windows'."""
        from config import load_config

        # Agent is Windows (.msi installer)
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42,
            "user_id": 1,
            "subnet_index": 5,
            "agent_id": 1,
            "instance_config": None,  # Use default config
            "agent_s3_key": "agents/xdr-installer.msi",
            "agent_os_slug": "windows",  # Windows agent!
        })

        result = load_config()

        # Victim should be Windows
        victim = result.instances[1]
        assert victim.role == "victim"
        assert victim.os_type == "windows", f"Expected 'windows' but got '{victim.os_type}'"

    def test_linux_debian_agent_creates_ubuntu_victim(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """When agent OS is 'linux-debian', victim os_type should be 'ubuntu'."""
        from config import load_config

        # Agent is Linux Debian (.deb installer)
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42,
            "user_id": 1,
            "subnet_index": 5,
            "agent_id": 1,
            "instance_config": None,
            "agent_s3_key": "agents/xdr-installer.deb",
            "agent_os_slug": "linux-debian",
        })

        result = load_config()

        # Victim should be Ubuntu (Linux)
        victim = result.instances[1]
        assert victim.role == "victim"
        assert victim.os_type == "ubuntu", f"Expected 'ubuntu' but got '{victim.os_type}'"

    def test_linux_rhel_agent_creates_ubuntu_victim(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """When agent OS is 'linux-rhel', victim os_type should be 'ubuntu'."""
        from config import load_config

        # Agent is Linux RHEL (.rpm installer)
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42,
            "user_id": 1,
            "subnet_index": 5,
            "agent_id": 1,
            "instance_config": None,
            "agent_s3_key": "agents/xdr-installer.rpm",
            "agent_os_slug": "linux-rhel",
        })

        result = load_config()

        # Victim should be Ubuntu (Linux) - we use Ubuntu as our Linux victim
        victim = result.instances[1]
        assert victim.role == "victim"
        assert victim.os_type == "ubuntu", f"Expected 'ubuntu' but got '{victim.os_type}'"

    def test_null_agent_os_defaults_to_ubuntu(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """When agent_os_slug is None, victim os_type should default to 'ubuntu'."""
        from config import load_config

        # No agent OS (legacy data or no agent)
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42,
            "user_id": 1,
            "subnet_index": 5,
            "agent_id": None,
            "instance_config": None,
            "agent_s3_key": None,
            "agent_os_slug": None,  # No OS info
        })

        result = load_config()

        # Should default to Ubuntu
        victim = result.instances[1]
        assert victim.role == "victim"
        assert victim.os_type == "ubuntu", f"Expected 'ubuntu' but got '{victim.os_type}'"

    def test_empty_agent_os_defaults_to_ubuntu(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """When agent_os_slug is empty string, victim os_type should default to 'ubuntu'."""
        from config import load_config

        mocker.patch("config.get_range_from_db", return_value={
            "id": 42,
            "user_id": 1,
            "subnet_index": 5,
            "agent_id": 1,
            "instance_config": None,
            "agent_s3_key": "agents/xdr.tar.gz",
            "agent_os_slug": "",  # Empty string
        })

        result = load_config()

        # Should default to Ubuntu
        victim = result.instances[1]
        assert victim.role == "victim"
        assert victim.os_type == "ubuntu", f"Expected 'ubuntu' but got '{victim.os_type}'"


class TestDCConfiguration:
    """Tests for Domain Controller configuration support."""

    def test_instance_config_supports_dc_config(self):
        """InstanceConfig should accept dc_config dict."""
        config = InstanceConfig(
            role="dc",
            os_type="windows",
            instance_type="t3.large",
            dc_config={
                "domain_name": "internal.shifter",
                "netbios_name": "SHIFTER",
            }
        )
        assert config.dc_config is not None
        assert config.dc_config["domain_name"] == "internal.shifter"
        assert config.dc_config["netbios_name"] == "SHIFTER"

    def test_instance_config_dc_config_optional(self):
        """dc_config should be optional (None by default)."""
        config = InstanceConfig(
            role="victim",
            os_type="ubuntu",
            instance_type="t3.small",
        )
        assert config.dc_config is None

    def test_instance_config_supports_join_domain(self):
        """InstanceConfig should support join_domain flag."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
            join_domain=True,
        )
        assert config.join_domain is True

    def test_instance_config_join_domain_default_false(self):
        """join_domain should default to False."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
        )
        assert config.join_domain is False

    def test_instance_config_supports_dc_config_param_name(self):
        """InstanceConfig should support dc_config_param_name for domain members."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
            join_domain=True,
            dc_config_param_name="/shifter/dev/range/42/dc-config",
        )
        assert config.dc_config_param_name == "/shifter/dev/range/42/dc-config"

    def test_instance_config_dc_config_param_name_optional(self):
        """dc_config_param_name should be optional (None by default)."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
        )
        assert config.dc_config_param_name is None


class TestLoadConfigDCSupport:
    """Tests for load_config parsing DC configuration from database.

    Uses mock_pulumi_config fixture from conftest.py.
    """

    def test_load_config_parses_dc_config_from_db(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should parse dc_config from instance_config JSON."""
        from config import load_config

        custom_config = [
            {"role": "dc", "os": "windows", "instance_type": "t3.large",
             "dc_config": {"domain_name": "test.local", "netbios_name": "TEST"}},
        ]
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": custom_config,
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert len(result.instances) == 1
        dc_instance = result.instances[0]
        assert dc_instance.role == "dc"
        assert dc_instance.dc_config is not None
        assert dc_instance.dc_config["domain_name"] == "test.local"
        assert dc_instance.dc_config["netbios_name"] == "TEST"

    def test_load_config_parses_join_domain_from_db(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should parse join_domain flag from instance_config JSON."""
        from config import load_config

        custom_config = [
            {"role": "victim", "os": "windows", "instance_type": "t3.medium",
             "join_domain": True},
        ]
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": custom_config,
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert len(result.instances) == 1
        victim_instance = result.instances[0]
        assert victim_instance.join_domain is True

    def test_load_config_join_domain_defaults_false(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should default join_domain to False when not specified."""
        from config import load_config

        custom_config = [
            {"role": "victim", "os": "windows", "instance_type": "t3.medium"},
        ]
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": custom_config,
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert result.instances[0].join_domain is False


class TestConfigValidation:
    """Tests for configuration validation edge cases."""

    def test_instance_config_empty_string_values(self):
        """Empty string values should be handled."""
        config = InstanceConfig(
            role="victim",
            os_type="ubuntu",
            instance_type="t3.micro",
            agent_s3_key="",  # Empty string
            agent_presigned_url="",  # Empty string
        )
        assert config.agent_s3_key == ""
        assert config.agent_presigned_url == ""

    def test_range_config_multiple_instances(self):
        """RangeConfig should support multiple instances."""
        instances = [
            InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small"),
            InstanceConfig(role="attacker", os_type="kali", instance_type="t3.medium"),
            InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.micro"),
            InstanceConfig(role="victim", os_type="windows", instance_type="t3.medium"),
            InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.large"),
        ]

        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="prod",
            instances=instances,
            vpc_id="vpc-123",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-123",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-victim",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )

        assert len(config.instances) == 5
        assert sum(1 for i in config.instances if i.role == "attacker") == 2
        assert sum(1 for i in config.instances if i.role == "victim") == 3

    def test_range_config_empty_instances(self):
        """RangeConfig should allow empty instances list."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=5,
            environment="dev",
            instances=[],  # Empty
            vpc_id="vpc-123",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-123",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-victim",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )

        assert config.instances == []


class TestOsTypeKeySupport:
    """Tests for os_type key support in instance_config JSON.

    The Portal sends 'os_type' but we also support legacy 'os' key.
    Uses mock_pulumi_config fixture from conftest.py.
    """

    def test_load_config_supports_os_type_key(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should parse os_type key from instance_config JSON (Portal format)."""
        from config import load_config

        custom_config = [
            {"role": "attacker", "os_type": "kali", "instance_type": "t3.medium"},
            {"role": "victim", "os_type": "windows", "instance_type": "t3.medium"},
        ]
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": custom_config,
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert len(result.instances) == 2
        assert result.instances[0].os_type == "kali"
        assert result.instances[1].os_type == "windows"

    def test_load_config_supports_legacy_os_key(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should still support legacy 'os' key for backwards compatibility."""
        from config import load_config

        custom_config = [
            {"role": "victim", "os": "ubuntu", "instance_type": "t3.medium"},
        ]
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": custom_config,
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert result.instances[0].os_type == "ubuntu"

    def test_load_config_os_type_takes_precedence_over_os(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """os_type key should take precedence over legacy os key if both present."""
        from config import load_config

        custom_config = [
            {"role": "victim", "os_type": "windows", "os": "ubuntu", "instance_type": "t3.medium"},
        ]
        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": custom_config,
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert result.instances[0].os_type == "windows"

    def test_load_config_dc_security_group_id_loaded(
        self, mock_pulumi_config, mocker, mock_boto3_clients
    ):
        """load_config should load dc_security_group_id from Pulumi config."""
        from config import load_config

        mocker.patch("config.get_range_from_db", return_value={
            "id": 42, "user_id": 1, "subnet_index": 5,
            "agent_id": None, "instance_config": [],
            "agent_s3_key": None, "agent_os_slug": None,
        })

        result = load_config()

        assert result.dc_security_group_id == "sg-dc-test"
