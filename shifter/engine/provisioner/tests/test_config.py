"""Configuration tests for Shifter Engine.

Tests config loading from Pulumi config and database.
Uses the new schema where range_config contains the full RangeSpec JSON.
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
    """Tests for database range loading with new schema."""

    def test_get_range_from_db_success(self, mock_boto3_clients, mock_env_vars_minimal):
        """Range data should be loaded with range_config JSON."""
        with patch("psycopg.connect") as mock_connect:
            range_config = {
                "scenario_id": "basic",
                "user_id": 1,
                "instances": [
                    {"role": "attacker", "os_type": "kali", "uuid": "uuid-1"},
                    {
                        "role": "victim",
                        "os_type": "ubuntu",
                        "uuid": "uuid-2",
                        "agent": {"s3_key": "agents/xdr.tar.gz", "filename": "xdr.tar.gz"},
                    },
                ],
            }
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                42,  # id
                1,  # user_id
                range_config,  # range_config JSON
                False,  # ngfw_enabled
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
            assert result["range_config"] == range_config
            assert result["ngfw_enabled"] is False

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

    def test_get_range_from_db_ngfw_enabled(self, mock_boto3_clients, mock_env_vars_minimal):
        """Range with ngfw_id should have ngfw_enabled=True."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (
                42,  # id
                1,  # user_id
                {"scenario_id": "basic", "user_id": 1, "instances": []},
                True,  # ngfw_enabled (ngfw_id IS NOT NULL)
            )
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["ngfw_enabled"] is True


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

    def test_instance_config_all_fields(self):
        """All fields should be populated."""
        config = InstanceConfig(
            role="victim",
            os_type="windows",
            instance_type="t3.medium",
            agent_s3_key="agents/xdr.msi",
            agent_presigned_url="https://s3.example.com/signed",
        )
        assert config.role == "victim"
        assert config.os_type == "windows"
        assert config.instance_type == "t3.medium"
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
        assert config.agent_s3_key is None


class TestRangeConfigDataclass:
    """Tests for the RangeConfig dataclass."""

    def test_range_config_required_fields(self):
        """All required fields should be present."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
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
        assert config.environment == "dev"
        assert len(config.instances) == 1
        assert config.vpc_id == "vpc-123"

    def test_range_config_optional_defaults(self):
        """portal_vpc_cidr should default to empty string."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
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

    def test_range_config_ngfw_defaults(self):
        """NGFW fields should have proper defaults."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
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

        assert config.ngfw_enabled is False
        assert config.ngfw_ami_id == ""
        assert config.ngfw_instance_type == "m5.xlarge"
        assert config.ngfw_security_group_id == ""


class TestLoadConfigIntegration:
    """Integration tests for load_config function with new schema."""

    @pytest.fixture
    def mock_db_range_data(self, mocker):
        """Mock get_range_from_db to return test data with new schema."""

        def _mock_db(range_id, range_config=None, ngfw_enabled=False):
            mock_data = {
                "id": range_id,
                "user_id": 1,
                "range_config": range_config or {"scenario_id": "basic", "user_id": 1, "instances": []},
                "ngfw_enabled": ngfw_enabled,
            }
            mocker.patch("config.get_range_from_db", return_value=mock_data)
            return mock_data

        return _mock_db

    def test_load_config_returns_range_config(self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients):
        """load_config should return a RangeConfig with all fields populated."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "scenario_id": "basic",
                "user_id": 1,
                "instances": [
                    {"role": "attacker", "os_type": "kali", "uuid": "uuid-1"},
                    {"role": "victim", "os_type": "ubuntu", "uuid": "uuid-2"},
                ],
            },
        )

        result = load_config()

        assert isinstance(result, RangeConfig)
        assert result.range_id == 42
        assert result.user_id == 1
        assert result.environment == "dev"
        assert result.vpc_id == "vpc-test123"
        assert len(result.instances) == 2

    def test_load_config_parses_instances_from_range_config(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """Instances should be parsed from range_config.instances."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "scenario_id": "basic",
                "user_id": 1,
                "instances": [
                    {"role": "attacker", "os_type": "kali", "uuid": "uuid-1"},
                    {
                        "role": "victim",
                        "os_type": "ubuntu",
                        "uuid": "uuid-2",
                        "agent": {"s3_key": "agents/xdr.tar.gz", "filename": "xdr.tar.gz"},
                    },
                ],
            },
        )

        result = load_config()

        assert len(result.instances) == 2
        assert result.instances[0].role == "attacker"
        assert result.instances[0].os_type == "kali"
        assert result.instances[1].role == "victim"
        assert result.instances[1].os_type == "ubuntu"
        assert result.instances[1].agent_s3_key == "agents/xdr.tar.gz"

    def test_load_config_generates_presigned_url(self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients):
        """Presigned URL should be generated for agents with s3_key."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "scenario_id": "basic",
                "user_id": 1,
                "instances": [
                    {
                        "role": "victim",
                        "os_type": "ubuntu",
                        "agent": {"s3_key": "agents/xdr.tar.gz", "filename": "xdr.tar.gz"},
                    },
                ],
            },
        )

        result = load_config()

        victim = result.instances[0]
        assert victim.agent_presigned_url == "https://s3.example.com/presigned-url"
        mock_boto3_clients["s3"].generate_presigned_url.assert_called()

    def test_load_config_no_presigned_url_without_agent(
        self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients
    ):
        """No presigned URL when no agent in instance."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={
                "scenario_id": "basic",
                "user_id": 1,
                "instances": [
                    {"role": "attacker", "os_type": "kali"},  # No agent
                ],
            },
        )

        result = load_config()

        attacker = result.instances[0]
        assert attacker.agent_presigned_url is None

    def test_load_config_empty_instances(self, mock_pulumi_config, mock_db_range_data, mock_boto3_clients):
        """Empty instances list should work."""
        from config import load_config

        mock_db_range_data(
            42,
            range_config={"scenario_id": "basic", "user_id": 1, "instances": []},
        )

        result = load_config()

        assert result.instances == []


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
        """load_config should parse dc_config from range_config.instances."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "range_config": {
                    "scenario_id": "ad_lab",
                    "user_id": 1,
                    "instances": [
                        {
                            "role": "dc",
                            "os_type": "windows",
                            "dc_config": {"domain_name": "test.local", "netbios_name": "TEST"},
                        },
                    ],
                },
                "ngfw_enabled": False,
            },
        )

        result = load_config()

        assert len(result.instances) == 1
        dc_instance = result.instances[0]
        assert dc_instance.role == "dc"
        assert dc_instance.dc_config["domain_name"] == "test.local"

    def test_load_config_parses_join_domain(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """load_config should parse join_domain from range_config.instances."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "range_config": {
                    "scenario_id": "ad_lab",
                    "user_id": 1,
                    "instances": [
                        {"role": "victim", "os_type": "windows", "join_domain": True},
                    ],
                },
                "ngfw_enabled": False,
            },
        )

        result = load_config()

        assert result.instances[0].join_domain is True


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
                "range_config": {
                    "scenario_id": "basic",
                    "user_id": 1,
                    "instances": [{"role": "attacker", "os_type": "kali"}],
                },
                "ngfw_enabled": False,
            },
        )

        result = load_config()

        assert result.instances[0].instance_type == os.environ["KALI_INSTANCE_TYPE"]

    def test_victim_uses_victim_instance_type(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """Victim role should use VICTIM_INSTANCE_TYPE from environment."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "range_config": {
                    "scenario_id": "basic",
                    "user_id": 1,
                    "instances": [{"role": "victim", "os_type": "ubuntu"}],
                },
                "ngfw_enabled": False,
            },
        )

        result = load_config()

        assert result.instances[0].instance_type == os.environ["VICTIM_INSTANCE_TYPE"]

    def test_dc_uses_dc_instance_type(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """DC role should use DC_INSTANCE_TYPE default (t3.large)."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "range_config": {
                    "scenario_id": "ad_lab",
                    "user_id": 1,
                    "instances": [{"role": "dc", "os_type": "windows"}],
                },
                "ngfw_enabled": False,
            },
        )

        result = load_config()

        assert result.instances[0].instance_type == "t3.large"


class TestLoadConfigNGFW:
    """Tests for NGFW config loading from environment variables."""

    def test_load_config_loads_ngfw_from_env(self, mock_pulumi_config, mocker, mock_boto3_clients):
        """load_config should load NGFW settings from environment variables."""
        from config import load_config

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "range_config": {"scenario_id": "basic", "user_id": 1, "instances": []},
                "ngfw_enabled": True,
            },
        )

        with patch.dict(
            os.environ,
            {
                "NGFW_AMI_ID": "ami-vmseries-env",
                "NGFW_INSTANCE_TYPE": "m5.xlarge",
                "NGFW_SECURITY_GROUP_ID": "sg-ngfw-env",
            },
        ):
            result = load_config()

        assert result.ngfw_enabled is True
        assert result.ngfw_ami_id == "ami-vmseries-env"
        assert result.ngfw_instance_type == "m5.xlarge"
        assert result.ngfw_security_group_id == "sg-ngfw-env"


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
