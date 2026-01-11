"""Configuration tests for Shifter Engine.

Tests config loading from Pulumi config and database.
Uses the new subnet-based schema where range_config contains subnets with instances.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    InstanceConfig,
    RangeConfig,
    SubnetConfig,
    _build_instance_config,
    _build_subnet_configs,
    decrypt_field,
    generate_presigned_url,
    get_range_from_db,
)


class TestGeneratePresignedUrl:
    """Tests for S3 presigned URL generation."""

    def test_generate_presigned_url_success(self, mock_boto3_clients):
        """Valid S3 presigned URL should be returned."""
        url = generate_presigned_url("test-bucket", "agents/installer.sh")
        assert url == "https://s3.example.com/presigned-url"

    def test_generate_presigned_url_custom_expiry(self, mock_boto3_clients):
        """Custom expires_in value should be used."""
        generate_presigned_url("test-bucket", "key", expires_in=7200)

        # Verify the S3 client was called with custom expiry
        mock_boto3_clients["s3"].generate_presigned_url.assert_called_once()
        call_kwargs = mock_boto3_clients["s3"].generate_presigned_url.call_args
        assert call_kwargs[1]["ExpiresIn"] == 7200

    def test_generate_presigned_url_default_expiry(self, mock_boto3_clients):
        """Default expiry should be 3600 seconds."""
        generate_presigned_url("test-bucket", "key")

        call_kwargs = mock_boto3_clients["s3"].generate_presigned_url.call_args
        assert call_kwargs[1]["ExpiresIn"] == 3600

    def test_generate_presigned_url_params(self, mock_boto3_clients):
        """Correct parameters should be passed to S3 client."""
        generate_presigned_url("my-bucket", "path/to/file.tar.gz")

        mock_boto3_clients["s3"].generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/file.tar.gz"},
            ExpiresIn=3600,
        )


class TestGetRangeFromDb:
    """Tests for database range loading with new subnet-based schema."""

    def test_get_range_from_db_success(
        self, mock_boto3_clients, mock_env_vars_minimal, sample_db_range_row
    ):
        """Range data should be loaded with subnets and gwlb_service_name."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = sample_db_range_row
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["id"] == 42
            assert result["user_id"] == 1
            assert result["request_uuid"] == "request-uuid-12345"
            assert "subnets" in result["range_config"]
            assert result["ngfw_enabled"] is False
            assert result["gwlb_service_name"] == ""

    def test_get_range_from_db_not_found(self, mock_boto3_clients, mock_env_vars_minimal):
        """ValueError should be raised for missing range."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            with pytest.raises(ValueError, match="Range 999 not found"):
                get_range_from_db(999)

    def test_get_range_from_db_with_ngfw(
        self, mock_boto3_clients, mock_env_vars_minimal, sample_db_range_row_with_ngfw
    ):
        """Range with NGFW should have ngfw_enabled=True and gwlb_service_name."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = sample_db_range_row_with_ngfw
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["ngfw_enabled"] is True
            assert result["gwlb_service_name"] == "com.amazonaws.vpce.us-east-2.vpce-svc-ngfw123"


class TestSubnetConfigDataclass:
    """Tests for the SubnetConfig dataclass."""

    def test_subnet_config_required_fields(self):
        """SubnetConfig requires name, uuid, and instances."""
        config = SubnetConfig(
            name="attack",
            uuid="subnet-uuid-123",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small")
            ],
        )
        assert config.name == "attack"
        assert config.uuid == "subnet-uuid-123"
        assert len(config.instances) == 1
        assert config.connected_to == []

    def test_subnet_config_with_connected_to(self):
        """SubnetConfig should accept connected_to list."""
        config = SubnetConfig(
            name="attack",
            uuid="subnet-uuid-123",
            instances=[
                InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small")
            ],
            connected_to=["target", "dc_network"],
        )
        assert config.connected_to == ["target", "dc_network"]

    def test_subnet_config_multiple_instances(self):
        """SubnetConfig can have multiple instances."""
        config = SubnetConfig(
            name="servers",
            uuid="subnet-uuid-456",
            instances=[
                InstanceConfig(role="victim", os_type="ubuntu", instance_type="t3.micro"),
                InstanceConfig(role="victim", os_type="windows", instance_type="t3.medium"),
            ],
        )
        assert len(config.instances) == 2
        assert config.instances[0].os_type == "ubuntu"
        assert config.instances[1].os_type == "windows"


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
        assert config.agent_s3_key is None
        assert config.agent_presigned_url is None
        assert config.dc_config is None
        assert config.join_domain is False

    def test_instance_config_all_fields(self):
        """All fields should be populated."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
            agent_s3_key="agents/xdr.msi",
            agent_presigned_url="https://s3.example.com/signed",
            dc_config={"domain_name": "test.local", "netbios_name": "TEST"},
            join_domain=True,
        )
        assert config.role == "victim"
        assert config.os_type == "windows"
        assert config.agent_s3_key == "agents/xdr.msi"
        assert config.dc_config["domain_name"] == "test.local"
        assert config.join_domain is True

    def test_instance_config_attacker(self):
        """Attacker config should not have agent fields."""
        config = InstanceConfig(
            role="attacker",
            os_type="kali",
            instance_type="t3.small",
        )
        assert config.role == "attacker"
        assert config.agent_s3_key is None


class TestRangeConfigDataclass:
    """Tests for the RangeConfig dataclass."""

    def test_range_config_required_fields(self):
        """All required fields should be present."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            request_uuid="request-uuid-123",
            environment="dev",
            subnets=[
                SubnetConfig(
                    name="attack",
                    uuid="subnet-uuid-attack",
                    instances=[
                        InstanceConfig(role="attacker", os_type="kali", instance_type="t3.small")
                    ],
                ),
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
        assert config.request_uuid == "request-uuid-123"
        assert config.environment == "dev"
        assert len(config.subnets) == 1
        assert config.subnets[0].name == "attack"
        assert config.vpc_id == "vpc-123"
        assert config.gwlb_service_name == ""

    def test_range_config_with_ngfw(self):
        """RangeConfig with NGFW should have gwlb_service_name."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            request_uuid="request-uuid-123",
            environment="dev",
            subnets=[],
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
            gwlb_service_name="com.amazonaws.vpce.us-east-2.vpce-svc-ngfw",
            ngfw_enabled=True,
        )

        assert config.ngfw_enabled is True
        assert config.gwlb_service_name == "com.amazonaws.vpce.us-east-2.vpce-svc-ngfw"


class TestBuildInstanceConfig:
    """Tests for _build_instance_config helper function."""

    def test_build_instance_config_basic(self):
        """Basic instance config should be built correctly."""
        inst = {"role": "attacker", "os_type": "kali"}
        get_presigned_url = lambda s3_key: None

        config = _build_instance_config(inst, get_presigned_url)

        assert config.role == "attacker"
        assert config.os_type == "kali"
        assert config.instance_type == os.environ["KALI_INSTANCE_TYPE"]

    def test_build_instance_config_with_agent(self, mock_boto3_clients):
        """Instance with agent should get presigned URL."""
        inst = {
            "role": "victim",
            "os_type": "ubuntu",
            "agent": {"s3_key": "agents/xdr.tar.gz"},
        }
        get_presigned_url = lambda s3_key: (
            f"https://s3.example.com/{s3_key}" if s3_key else None
        )

        config = _build_instance_config(inst, get_presigned_url)

        assert config.agent_s3_key == "agents/xdr.tar.gz"
        assert config.agent_presigned_url == "https://s3.example.com/agents/xdr.tar.gz"

    def test_build_instance_config_with_dc_config(self):
        """DC instance should have dc_config extracted."""
        inst = {
            "role": "dc",
            "os_type": "windows",
            "dc_config": {"domain_name": "test.local", "netbios_name": "TEST"},
        }
        get_presigned_url = lambda s3_key: None

        config = _build_instance_config(inst, get_presigned_url)

        assert config.role == "dc"
        assert config.dc_config is not None
        assert config.dc_config["domain_name"] == "test.local"
        assert config.dc_config["netbios_name"] == "TEST"

    def test_build_instance_config_join_domain(self):
        """join_domain flag should be extracted."""
        inst = {
            "role": "victim",
            "os_type": "windows",
            "join_domain": True,
        }
        get_presigned_url = lambda s3_key: None

        config = _build_instance_config(inst, get_presigned_url)

        assert config.join_domain is True


class TestBuildSubnetConfigs:
    """Tests for _build_subnet_configs helper function."""

    def test_build_subnet_configs_basic(self):
        """Basic subnet list should be built correctly."""
        spec_subnets = [
            {
                "name": "attack",
                "uuid": "subnet-uuid-attack",
                "instances": [{"role": "attacker", "os_type": "kali"}],
            },
        ]
        get_presigned_url = lambda s3_key: None

        subnets = _build_subnet_configs(spec_subnets, get_presigned_url)

        assert len(subnets) == 1
        assert subnets[0].name == "attack"
        assert subnets[0].uuid == "subnet-uuid-attack"
        assert len(subnets[0].instances) == 1

    def test_build_subnet_configs_with_connected_to(self):
        """connected_to should be extracted."""
        spec_subnets = [
            {
                "name": "attack",
                "uuid": "subnet-uuid-attack",
                "instances": [{"role": "attacker", "os_type": "kali"}],
                "connected_to": ["target", "dc_network"],
            },
        ]
        get_presigned_url = lambda s3_key: None

        subnets = _build_subnet_configs(spec_subnets, get_presigned_url)

        assert subnets[0].connected_to == ["target", "dc_network"]

    def test_build_subnet_configs_missing_name(self):
        """Missing subnet name should raise ValueError."""
        spec_subnets = [
            {
                "uuid": "subnet-uuid-attack",
                "instances": [{"role": "attacker", "os_type": "kali"}],
            },
        ]
        get_presigned_url = lambda s3_key: None

        with pytest.raises(ValueError, match="missing required 'name' field"):
            _build_subnet_configs(spec_subnets, get_presigned_url)

    def test_build_subnet_configs_missing_uuid(self):
        """Missing subnet uuid should raise ValueError."""
        spec_subnets = [
            {
                "name": "attack",
                "instances": [{"role": "attacker", "os_type": "kali"}],
            },
        ]
        get_presigned_url = lambda s3_key: None

        with pytest.raises(ValueError, match="missing required 'uuid' field"):
            _build_subnet_configs(spec_subnets, get_presigned_url)

    def test_build_subnet_configs_multiple(self):
        """Multiple subnets should be built correctly."""
        spec_subnets = [
            {
                "name": "attack",
                "uuid": "subnet-uuid-attack",
                "instances": [{"role": "attacker", "os_type": "kali"}],
                "connected_to": ["target"],
            },
            {
                "name": "target",
                "uuid": "subnet-uuid-target",
                "instances": [
                    {"role": "victim", "os_type": "ubuntu"},
                    {"role": "victim", "os_type": "windows"},
                ],
                "connected_to": [],
            },
        ]
        get_presigned_url = lambda s3_key: None

        subnets = _build_subnet_configs(spec_subnets, get_presigned_url)

        assert len(subnets) == 2
        assert subnets[0].name == "attack"
        assert subnets[1].name == "target"
        assert len(subnets[1].instances) == 2


class TestLoadConfigIntegration:
    """Integration tests for load_config function with new subnet schema."""

    @pytest.fixture
    def mock_db_range_data(self, mocker):
        """Mock get_range_from_db to return test data with new schema."""

        def _mock_db(range_id, range_config=None, ngfw_enabled=False, gwlb_service_name=""):
            mock_data = {
                "id": range_id,
                "user_id": 1,
                "request_uuid": "request-uuid-test",
                "range_config": range_config or {"subnets": []},
                "ngfw_enabled": ngfw_enabled,
                "gwlb_service_name": gwlb_service_name,
            }
            mocker.patch("config.get_range_from_db", return_value=mock_data)
            return mock_data

        return _mock_db

    def test_load_config_returns_range_config(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """load_config should return a RangeConfig with subnets."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "subnets": [
                    {
                        "name": "attack",
                        "uuid": "subnet-uuid-attack",
                        "instances": [{"role": "attacker", "os_type": "kali"}],
                    },
                    {
                        "name": "target",
                        "uuid": "subnet-uuid-target",
                        "instances": [{"role": "victim", "os_type": "ubuntu"}],
                    },
                ]
            },
        )

        result = load_config()

        assert isinstance(result, RangeConfig)
        assert result.range_id == 42
        assert result.user_id == 1
        assert result.request_uuid == "request-uuid-test"
        assert result.environment == "dev"
        assert result.vpc_id == "vpc-test123"
        assert len(result.subnets) == 2

    def test_load_config_parses_subnets(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """Subnets should be parsed from range_config.subnets."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "subnets": [
                    {
                        "name": "attack",
                        "uuid": "subnet-uuid-attack",
                        "instances": [{"role": "attacker", "os_type": "kali"}],
                        "connected_to": ["target"],
                    },
                    {
                        "name": "target",
                        "uuid": "subnet-uuid-target",
                        "instances": [
                            {
                                "role": "victim",
                                "os_type": "ubuntu",
                                "agent": {"s3_key": "agents/xdr.tar.gz"},
                            }
                        ],
                        "connected_to": [],
                    },
                ]
            },
        )

        result = load_config()

        assert len(result.subnets) == 2
        assert result.subnets[0].name == "attack"
        assert result.subnets[0].connected_to == ["target"]
        assert result.subnets[1].name == "target"
        assert len(result.subnets[1].instances) == 1
        assert result.subnets[1].instances[0].agent_s3_key == "agents/xdr.tar.gz"

    def test_load_config_generates_presigned_url(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """Presigned URL should be generated for agents with s3_key."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "subnets": [
                    {
                        "name": "target",
                        "uuid": "subnet-uuid-target",
                        "instances": [
                            {
                                "role": "victim",
                                "os_type": "ubuntu",
                                "agent": {"s3_key": "agents/xdr.tar.gz"},
                            }
                        ],
                    },
                ]
            },
        )

        result = load_config()

        victim = result.subnets[0].instances[0]
        assert victim.agent_presigned_url == "https://s3.example.com/presigned-url"
        mock_boto3_clients["s3"].generate_presigned_url.assert_called()

    def test_load_config_with_ngfw(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """load_config should include gwlb_service_name when NGFW enabled."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={"subnets": []},
            ngfw_enabled=True,
            gwlb_service_name="com.amazonaws.vpce.us-east-2.vpce-svc-ngfw123",
        )

        result = load_config()

        assert result.ngfw_enabled is True
        assert result.gwlb_service_name == "com.amazonaws.vpce.us-east-2.vpce-svc-ngfw123"

    def test_load_config_empty_subnets(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """Empty subnets list should work."""
        from config import load_config

        mock_db_range_data(42, range_config={"subnets": []})

        result = load_config()

        assert result.subnets == []


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
            },
        )
        assert config.dc_config is not None
        assert config.dc_config["domain_name"] == "internal.shifter"

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


class TestLoadConfigDCSupport:
    """Tests for load_config parsing DC configuration from new schema."""

    def test_load_config_parses_dc_config(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """load_config should parse dc_config from subnets."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "request_uuid": "request-uuid-dc",
                "range_config": {
                    "subnets": [
                        {
                            "name": "dc_network",
                            "uuid": "subnet-uuid-dc",
                            "instances": [
                                {
                                    "role": "dc",
                                    "os_type": "windows",
                                    "dc_config": {
                                        "domain_name": "test.local",
                                        "netbios_name": "TEST",
                                    },
                                },
                            ],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        assert len(result.subnets) == 1
        dc_instance = result.subnets[0].instances[0]
        assert dc_instance.role == "dc"
        assert dc_instance.dc_config["domain_name"] == "test.local"

    def test_load_config_parses_join_domain(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """load_config should parse join_domain from subnets."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "request_uuid": "request-uuid-join",
                "range_config": {
                    "subnets": [
                        {
                            "name": "workstations",
                            "uuid": "subnet-uuid-ws",
                            "instances": [
                                {"role": "victim", "os_type": "windows", "join_domain": True},
                            ],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        assert result.subnets[0].instances[0].join_domain is True


class TestInstanceTypeDefaults:
    """Tests for instance type defaults from catalog."""

    def test_attacker_uses_kali_instance_type(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """Attacker role should use KALI_INSTANCE_TYPE from environment."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "request_uuid": "request-uuid-types",
                "range_config": {
                    "subnets": [
                        {
                            "name": "attack",
                            "uuid": "subnet-uuid-attack",
                            "instances": [{"role": "attacker", "os_type": "kali"}],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        assert result.subnets[0].instances[0].instance_type == os.environ["KALI_INSTANCE_TYPE"]

    def test_victim_uses_victim_instance_type(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """Victim role should use VICTIM_INSTANCE_TYPE from environment."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "request_uuid": "request-uuid-victim",
                "range_config": {
                    "subnets": [
                        {
                            "name": "target",
                            "uuid": "subnet-uuid-target",
                            "instances": [{"role": "victim", "os_type": "ubuntu"}],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        assert result.subnets[0].instances[0].instance_type == os.environ["VICTIM_INSTANCE_TYPE"]

    def test_dc_uses_dc_instance_type(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """DC role should use DC_INSTANCE_TYPE default (t3.large)."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "request_uuid": "request-uuid-dc-type",
                "range_config": {
                    "subnets": [
                        {
                            "name": "dc_network",
                            "uuid": "subnet-uuid-dc",
                            "instances": [{"role": "dc", "os_type": "windows"}],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        assert result.subnets[0].instances[0].instance_type == "t3.large"


class TestDecryptField:
    """Tests for decrypt_field function used for encrypted database fields."""

    # Same test key as Django settings (for testing only)
    # pragma: allowlist secret
    TEST_ENCRYPTION_KEY = "VbMOEgh9VmS5lr0EsIS2sD9X1iy-Qd12i4kVZHdgPVE="  # nosec B105

    def test_decrypt_field_empty_value_returns_empty(self):
        """Empty string input should return empty string."""
        assert decrypt_field("") == ""

    def test_decrypt_field_no_key_returns_as_is(self, mocker):
        """Without FIELD_ENCRYPTION_KEY, value is returned as-is."""
        mocker.patch.dict(os.environ, {}, clear=True)
        if "FIELD_ENCRYPTION_KEY" in os.environ:
            del os.environ["FIELD_ENCRYPTION_KEY"]

        result = decrypt_field("some-value")
        assert result == "some-value"

    def test_decrypt_field_valid_encrypted_value(self, mocker):
        """Valid Fernet-encrypted value should be decrypted."""
        import base64

        from cryptography.fernet import Fernet

        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": self.TEST_ENCRYPTION_KEY})

        fernet = Fernet(self.TEST_ENCRYPTION_KEY.encode())
        plaintext = "my-secret-pin-value"
        encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
        encrypted_value = base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")

        result = decrypt_field(encrypted_value)
        assert result == plaintext

    def test_decrypt_field_invalid_value_returns_as_is(self, mocker):
        """Invalid encrypted value should return as-is (backward compatibility)."""
        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": self.TEST_ENCRYPTION_KEY})

        result = decrypt_field("not-encrypted-just-plaintext")
        assert result == "not-encrypted-just-plaintext"
