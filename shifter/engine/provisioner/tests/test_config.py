"""Configuration tests for Shifter Engine.

Tests config loading from Pulumi config and database.
Focuses on actual business logic: parsing, validation, and error handling.
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

    def test_generates_url_with_correct_params(self, mock_boto3_clients):
        """Presigned URL should be generated with correct bucket/key params."""
        url = generate_presigned_url("my-bucket", "path/to/file.tar.gz")

        assert url == "https://s3.example.com/presigned-url"
        mock_boto3_clients["s3"].generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "path/to/file.tar.gz"},
            ExpiresIn=3600,
        )

    def test_custom_expiry_passed_to_s3(self, mock_boto3_clients):
        """Custom expires_in value should be passed to S3."""
        generate_presigned_url("bucket", "key", expires_in=7200)

        call_kwargs = mock_boto3_clients["s3"].generate_presigned_url.call_args
        assert call_kwargs[1]["ExpiresIn"] == 7200


class TestGetRangeFromDb:
    """Tests for database range loading."""

    def test_loads_range_with_subnets(self, mock_boto3_clients, mock_env_vars_minimal, sample_db_range_row):
        """Range data should be loaded with subnets structure."""
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

    def test_raises_value_error_when_not_found(self, mock_boto3_clients, mock_env_vars_minimal):
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

    def test_ngfw_flag_from_range_config(
        self, mock_boto3_clients, mock_env_vars_minimal, sample_db_range_row_with_ngfw
    ):
        """Range with ngfw: true in range_config should have ngfw_enabled=True."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            # First call returns range row, second call returns NGFW service name
            mock_cursor.fetchone.side_effect = [
                sample_db_range_row_with_ngfw,
                ("com.amazonaws.vpce.us-east-2.vpce-svc-test123", 123),  # NGFW lookup: (service_name, instance_id)
            ]
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["ngfw_enabled"] is True
            assert result["gwlb_service_name"] == "com.amazonaws.vpce.us-east-2.vpce-svc-test123"


class TestDataclassDefaults:
    """Tests for dataclass default values and field handling."""

    def test_instance_config_defaults_and_dc_fields(self):
        """InstanceConfig optional fields should have correct defaults and accept dc_config."""
        # Test defaults
        config = InstanceConfig(
            uuid="inst-uuid-001",
            role="victim",
            os_type="ubuntu",
            instance_type="t3.micro",
        )
        assert config.agent_s3_key is None
        assert config.agent_presigned_url is None
        assert config.dc_config is None
        assert config.join_domain is False

        # Test DC instance with dc_config
        dc_config = InstanceConfig(
            uuid="inst-uuid-002",
            role="dc",
            os_type="windows",
            instance_type="t3.large",
            dc_config={"domain_name": "test.local", "netbios_name": "TEST"},
        )
        assert dc_config.dc_config["domain_name"] == "test.local"
        assert dc_config.dc_config["netbios_name"] == "TEST"

    def test_subnet_config_connected_to_default(self):
        """SubnetConfig connected_to should default to empty list."""
        config = SubnetConfig(
            name="attack",
            uuid="subnet-uuid-001",
            instances=[
                InstanceConfig(
                    uuid="inst-uuid-003",
                    role="attacker",
                    os_type="kali",
                    instance_type="t3.small",
                )
            ],
        )
        assert config.connected_to == []

    def test_range_config_defaults_and_optional_fields(self):
        """RangeConfig optional fields should have correct defaults."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            request_uuid="request-uuid-001",
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
            portal_vpc_cidr="10.0.0.0/16",
        )
        assert config.gwlb_service_name == ""
        assert config.ngfw_enabled is False
        assert config.dc_ami_id == ""
        assert config.portal_vpc_cidr == "10.0.0.0/16"
        assert config.portal_vpc_peering_id == ""


class TestBuildInstanceConfig:
    """Tests for _build_instance_config helper function."""

    def test_basic_instance(self):
        """Basic instance config should use role-based instance type."""
        inst = {"uuid": "inst-uuid-001", "role": "attacker", "os_type": "kali"}

        config = _build_instance_config(inst, lambda s3_key: None, "attack")

        assert config.role == "attacker"
        assert config.os_type == "kali"
        assert config.instance_type == os.environ["KALI_INSTANCE_TYPE"]

    def test_instance_with_agent_gets_presigned_url(self, mock_boto3_clients):
        """Instance with agent should get presigned URL."""
        inst = {
            "uuid": "inst-uuid-002",
            "role": "victim",
            "os_type": "ubuntu",
            "agent": {"s3_key": "agents/xdr.tar.gz"},
        }

        config = _build_instance_config(
            inst,
            lambda s3_key: f"https://s3.example.com/{s3_key}" if s3_key else None,
            "target",
        )

        assert config.agent_s3_key == "agents/xdr.tar.gz"
        assert config.agent_presigned_url == "https://s3.example.com/agents/xdr.tar.gz"

    def test_dc_instance_extracts_dc_config(self):
        """DC instance should have dc_config extracted."""
        inst = {
            "uuid": "inst-uuid-003",
            "role": "dc",
            "os_type": "windows",
            "dc_config": {"domain_name": "test.local", "netbios_name": "TEST"},
        }

        config = _build_instance_config(inst, lambda s3_key: None, "dc_network")

        assert config.role == "dc"
        assert config.dc_config["domain_name"] == "test.local"

    def test_join_domain_flag_extracted(self):
        """join_domain flag should be extracted."""
        inst = {
            "uuid": "inst-uuid-004",
            "role": "victim",
            "os_type": "windows",
            "join_domain": True,
        }

        config = _build_instance_config(inst, lambda s3_key: None, "workstations")

        assert config.join_domain is True


class TestBuildSubnetConfigs:
    """Tests for _build_subnet_configs validation and parsing."""

    def test_parses_basic_subnet(self):
        """Basic subnet should be parsed correctly."""
        spec_subnets = [
            {
                "name": "attack",
                "uuid": "subnet-uuid-001",
                "instances": [{"uuid": "inst-uuid-005", "role": "attacker", "os_type": "kali"}],
            },
        ]

        subnets = _build_subnet_configs(spec_subnets, lambda s3_key: None)

        assert len(subnets) == 1
        assert subnets[0].name == "attack"
        assert subnets[0].uuid == "subnet-uuid-001"

    def test_parses_connected_to(self):
        """connected_to should be extracted."""
        spec_subnets = [
            {
                "name": "attack",
                "uuid": "subnet-uuid-002",
                "instances": [{"uuid": "inst-uuid-006", "role": "attacker", "os_type": "kali"}],
                "connected_to": ["target", "dc_network"],
            },
        ]

        subnets = _build_subnet_configs(spec_subnets, lambda s3_key: None)

        assert subnets[0].connected_to == ["target", "dc_network"]

    def test_missing_name_raises_error(self):
        """Missing subnet name should raise ValueError."""
        spec_subnets = [
            {
                "uuid": "subnet-uuid-003",
                "instances": [{"uuid": "inst-uuid-007", "role": "attacker", "os_type": "kali"}],
            },
        ]

        with pytest.raises(ValueError, match="missing required 'name' field"):
            _build_subnet_configs(spec_subnets, lambda s3_key: None)

    def test_missing_uuid_raises_error(self):
        """Missing subnet uuid should raise ValueError."""
        spec_subnets = [
            {
                "name": "attack",
                "instances": [{"uuid": "inst-uuid-008", "role": "attacker", "os_type": "kali"}],
            },
        ]

        with pytest.raises(ValueError, match="missing required 'uuid' field"):
            _build_subnet_configs(spec_subnets, lambda s3_key: None)

    def test_parses_multiple_subnets_with_instances(self):
        """Multiple subnets with instances should be parsed correctly."""
        spec_subnets = [
            {
                "name": "attack",
                "uuid": "subnet-uuid-004",
                "instances": [{"uuid": "inst-uuid-009", "role": "attacker", "os_type": "kali"}],
            },
            {
                "name": "target",
                "uuid": "subnet-uuid-005",
                "instances": [
                    {"uuid": "inst-uuid-010", "role": "victim", "os_type": "ubuntu"},
                    {"uuid": "inst-uuid-011", "role": "victim", "os_type": "windows"},
                ],
            },
        ]

        subnets = _build_subnet_configs(spec_subnets, lambda s3_key: None)

        assert len(subnets) == 2
        assert len(subnets[1].instances) == 2


class TestLoadConfigIntegration:
    """Integration tests for load_config function."""

    @pytest.fixture
    def mock_db_range_data(self, mocker):
        """Mock get_range_from_db to return test data."""

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

    def test_returns_range_config_with_subnets(self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients):
        """load_config should return a RangeConfig with parsed subnets."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "subnets": [
                    {
                        "name": "attack",
                        "uuid": "subnet-uuid-attack",
                        "instances": [{"uuid": "inst-uuid-012", "role": "attacker", "os_type": "kali"}],
                        "connected_to": ["target"],
                    },
                    {
                        "name": "target",
                        "uuid": "subnet-uuid-target",
                        "instances": [
                            {
                                "uuid": "inst-uuid-013",
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

        assert isinstance(result, RangeConfig)
        assert result.range_id == 42
        assert len(result.subnets) == 2
        assert result.subnets[0].connected_to == ["target"]
        assert result.subnets[1].instances[0].agent_s3_key == "agents/xdr.tar.gz"

    def test_generates_presigned_urls_for_agents(self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients):
        """Presigned URL should be generated for instances with agents."""
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
                                "uuid": "inst-uuid-014",
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

        assert result.subnets[0].instances[0].agent_presigned_url == "https://s3.example.com/presigned-url"

    def test_includes_ngfw_config(self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients):
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

    def test_parses_dc_config_and_join_domain(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """load_config should parse dc_config and join_domain from subnets."""
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
                                    "uuid": "inst-uuid-015",
                                    "role": "dc",
                                    "os_type": "windows",
                                    "dc_config": {"domain_name": "test.local", "netbios_name": "TEST"},
                                },
                            ],
                        },
                        {
                            "name": "workstations",
                            "uuid": "subnet-uuid-ws",
                            "instances": [
                                {"uuid": "inst-uuid-016", "role": "victim", "os_type": "windows", "join_domain": True},
                            ],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        dc_instance = result.subnets[0].instances[0]
        assert dc_instance.dc_config["domain_name"] == "test.local"

        ws_instance = result.subnets[1].instances[0]
        assert ws_instance.join_domain is True

    def test_instance_type_defaults_by_role(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """Instance types should default based on role."""
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
                            "instances": [{"uuid": "inst-uuid-017", "role": "attacker", "os_type": "kali"}],
                        },
                        {
                            "name": "target",
                            "uuid": "subnet-uuid-target",
                            "instances": [{"uuid": "inst-uuid-018", "role": "victim", "os_type": "ubuntu"}],
                        },
                        {
                            "name": "dc_network",
                            "uuid": "subnet-uuid-dc",
                            "instances": [{"uuid": "inst-uuid-019", "role": "dc", "os_type": "windows"}],
                        },
                    ]
                },
                "ngfw_enabled": False,
                "gwlb_service_name": "",
            },
        )

        result = load_config()

        assert result.subnets[0].instances[0].instance_type == os.environ["KALI_INSTANCE_TYPE"]
        assert result.subnets[1].instances[0].instance_type == os.environ["VICTIM_INSTANCE_TYPE"]
        assert result.subnets[2].instances[0].instance_type == "t3.large"  # DC default


class TestDecryptField:
    """Tests for decrypt_field function for encrypted database fields."""

    # Test key for testing only
    # pragma: allowlist secret
    TEST_ENCRYPTION_KEY = "VbMOEgh9VmS5lr0EsIS2sD9X1iy-Qd12i4kVZHdgPVE="  # nosec B105

    def test_empty_value_returns_empty(self):
        """Empty string should return empty string."""
        assert decrypt_field("") == ""

    def test_no_key_returns_value_unchanged(self, mocker):
        """Without FIELD_ENCRYPTION_KEY, value is returned as-is."""
        mocker.patch.dict(os.environ, {}, clear=True)
        if "FIELD_ENCRYPTION_KEY" in os.environ:
            del os.environ["FIELD_ENCRYPTION_KEY"]

        result = decrypt_field("some-value")
        assert result == "some-value"

    def test_decrypts_valid_encrypted_value(self, mocker):
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

    def test_invalid_value_returns_unchanged(self, mocker):
        """Invalid encrypted value should return as-is (backward compatibility)."""
        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": self.TEST_ENCRYPTION_KEY})

        result = decrypt_field("not-encrypted-just-plaintext")
        assert result == "not-encrypted-just-plaintext"
