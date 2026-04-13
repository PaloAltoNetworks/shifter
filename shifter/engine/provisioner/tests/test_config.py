"""Configuration tests for Shifter Engine.

Tests for config utilities: presigned URLs, DB loading, dataclasses, and decryption.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    GDCNetworkAccessConfig,
    GDCPaloAltoVMSeriesConfig,
    GDCVMRuntimeConfig,
    GDCVMRuntimeProfile,
    InstanceConfig,
    RangeConfig,
    RangeNetworkConfig,
    SubnetConfig,
    decrypt_field,
    generate_presigned_url,
    get_range_availability_zone,
    get_range_from_db,
    load_gdc_network_access_config,
    load_gdc_palo_alto_vmseries_config,
    load_gdc_scenario_pod_config,
    load_gdc_vmruntime_config,
    load_range_network_config,
)


class TestGeneratePresignedUrl:
    """Tests for S3 presigned URL generation via cloud abstraction."""

    def test_generates_url_with_correct_params(self):
        """Presigned URL should be generated with correct bucket/key params."""
        mock_storage = MagicMock()
        mock_storage.generate_presigned_download_url.return_value = "https://s3.example.com/presigned-url"

        with patch("cloud.get_object_storage", return_value=mock_storage):
            url = generate_presigned_url("my-bucket", "path/to/file.tar.gz")

        assert url == "https://s3.example.com/presigned-url"
        mock_storage.generate_presigned_download_url.assert_called_once_with(
            bucket="my-bucket", key="path/to/file.tar.gz", expires_in=3600
        )

    def test_custom_expiry_passed_to_storage(self):
        """Custom expires_in value should be passed to ObjectStorage."""
        mock_storage = MagicMock()
        mock_storage.generate_presigned_download_url.return_value = "https://s3.example.com/presigned-url"

        with patch("cloud.get_object_storage", return_value=mock_storage):
            generate_presigned_url("bucket", "key", expires_in=7200)

        call_kwargs = mock_storage.generate_presigned_download_url.call_args
        assert call_kwargs[1]["expires_in"] == 7200


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
            # First call returns range row, second call returns NGFW data ENI ID
            mock_cursor.fetchone.side_effect = [
                sample_db_range_row_with_ngfw,
                (
                    {
                        "management_ip": "10.1.5.10",
                        "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
                        "data_eni_id": "eni-test123",
                    },
                    123,
                ),
            ]
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["ngfw_enabled"] is True
            assert result["ngfw_data_eni_id"] == "eni-test123"
            assert result["ngfw_attachment"]["attachment_mode"] == "aws-route-table-eni"
            assert result["ngfw_attachment"]["ssh_key_secret_ref"].endswith(":secret:key")

    def test_gcp_ngfw_attachment_uses_route_next_hop_state(
        self, mock_boto3_clients, mock_env_vars_minimal, sample_db_range_row_with_ngfw
    ):
        """GCP/GDC NGFWs should resolve attachable state without AWS ENI fields."""
        with patch("psycopg.connect") as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.side_effect = [
                sample_db_range_row_with_ngfw,
                (
                    {
                        "cloud_provider": "gcp",
                        "management_ip": "10.200.0.10",
                        "ssh_key_secret_id": "projects/test/secrets/ngfw-admin",
                        "route_next_hop_ip": "10.200.0.2",
                        "provider_metadata": {
                            "gcp": {
                                "attachment_mode": "gdc-static-route",
                            }
                        },
                    },
                    123,
                ),
            ]
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = get_range_from_db(42)

            assert result["ngfw_enabled"] is True
            assert result["ngfw_data_eni_id"] == ""
            assert result["ngfw_instance_id"] == 123
            assert result["ngfw_attachment"]["cloud_provider"] == "gcp"
            assert result["ngfw_attachment"]["route_next_hop_ip"] == "10.200.0.2"


class TestDataclassDefaults:
    """Tests for dataclass default values and field handling."""

    def test_instance_config_defaults_and_dc_fields(self):
        """InstanceConfig optional fields should have correct defaults and accept dc_config."""
        # Test defaults
        config = InstanceConfig(
            uuid="inst-uuid-001",
            name="target-ubuntu",
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
            name="dc-windows",
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
                    name="attacker-kali",
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
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-victim",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
            portal_vpc_cidr="10.0.0.0/16",
        )
        assert config.ngfw_data_eni_id == ""
        assert config.ngfw_attachment_mode == ""
        assert config.ngfw_route_next_hop_ip == ""
        assert config.ngfw_enabled is False
        assert config.dc_ami_id == ""
        assert config.portal_vpc_cidr == "10.0.0.0/16"
        assert config.portal_vpc_peering_id == ""

    def test_range_network_config_primary_portal_cidr(self):
        """RangeNetworkConfig should expose the first portal CIDR for legacy callers."""
        config = RangeNetworkConfig(
            network_id="projects/test/global/networks/range",
            network_cidr="10.50.0.0/16",
            network_region="us-central1",
            portal_network_cidrs=("10.40.0.0/20", "10.44.0.0/16"),
        )

        assert config.primary_portal_cidr == "10.40.0.0/20"


class TestRangeNetworkEnv:
    """Tests for provider-neutral range network env parsing."""

    def test_load_range_network_config_prefers_generic_env_names(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "RANGE_NETWORK_ID": "projects/test/global/networks/gcp-range",
                "RANGE_NETWORK_CIDR": "10.50.0.0/16",
                "RANGE_NETWORK_REGION": "us-central1",
                "PORTAL_NETWORK_CIDRS": "10.40.0.0/20,10.44.0.0/16",
                "RANGE_VPC_ID": "vpc-legacy",
                "RANGE_VPC_CIDR": "10.1.0.0/16",
            },
            clear=True,
        )

        config = load_range_network_config()

        assert config.network_id == "projects/test/global/networks/gcp-range"
        assert config.network_cidr == "10.50.0.0/16"
        assert config.network_region == "us-central1"
        assert config.portal_network_cidrs == ("10.40.0.0/20", "10.44.0.0/16")

    def test_load_range_network_config_falls_back_to_legacy_env_names(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "RANGE_VPC_ID": "vpc-legacy",
                "RANGE_VPC_CIDR": "10.1.0.0/16",
                "PORTAL_VPC_CIDR": "10.0.0.0/16",
                "AWS_REGION": "us-east-2",
            },
            clear=True,
        )

        config = load_range_network_config()

        assert config.network_id == "vpc-legacy"
        assert config.network_cidr == "10.1.0.0/16"
        assert config.network_region == "us-east-2"
        assert config.portal_network_cidrs == ("10.0.0.0/16",)

    def test_get_range_availability_zone_supports_legacy_and_generic_env_names(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "RANGE_AVAILABILITY_ZONE": "us-east-2a",
                "AVAILABILITY_ZONE": "us-east-2b",
            },
            clear=True,
        )

        assert get_range_availability_zone() == "us-central1-b"

    def test_load_gdc_network_access_config_reads_secret_bundle(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GDC_ACCESS_SECRET_ID": "projects/test/secrets/shifter-gcp-dev-gdc-access",
            },
            clear=True,
        )
        mock_secrets = mocker.Mock()
        mock_secrets.get_secret.return_value = """
        {
          "cluster_id": "cluster1",
          "region": "us-central1",
          "vxlan_cidr": "10.200.0.0/24",
          "network_interface": "vxlan0",
          "range_namespace_prefix": "range",
          "dns_nameservers": ["8.8.8.8", "1.1.1.1"],
          "static_ip_reservation_count": 6,
          "kubeconfig": "apiVersion: v1\\nclusters: []\\ncontexts: []\\ncurrent-context: ''\\nusers: []\\n"
        }
        """
        mocker.patch("cloud.get_secrets_store", return_value=mock_secrets)

        config = load_gdc_network_access_config()

        assert config == GDCNetworkAccessConfig(
            access_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-access",
            cluster_id="cluster1",
            region="us-central1",
            vxlan_cidr="10.200.0.0/24",
            network_interface="vxlan0",
            namespace_prefix="range",
            dns_nameservers=("8.8.8.8", "1.1.1.1"),
            static_ip_reservation_count=6,
            kubeconfig="apiVersion: v1\nclusters: []\ncontexts: []\ncurrent-context: ''\nusers: []",
        )

    def test_load_range_network_config_uses_gdc_access_bundle_when_active(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GDC_ACCESS_SECRET_ID": "projects/test/secrets/shifter-gcp-dev-gdc-access",
                "PORTAL_NETWORK_CIDRS": "10.40.0.0/20,10.44.0.0/16",
                "RANGE_NETWORK_ID": "projects/test/global/networks/legacy-range",
                "RANGE_NETWORK_CIDR": "10.50.0.0/16",
            },
            clear=True,
        )
        mock_secrets = mocker.Mock()
        mock_secrets.get_secret.return_value = """
        {
          "cluster_id": "cluster1",
          "region": "us-central1",
          "vxlan_cidr": "10.200.0.0/24",
          "kubeconfig": "apiVersion: v1\\nclusters: []\\ncontexts: []\\ncurrent-context: ''\\nusers: []\\n"
        }
        """
        mocker.patch("cloud.get_secrets_store", return_value=mock_secrets)

        config = load_range_network_config()

        assert config.network_id == "cluster1"
        assert config.network_cidr == "10.200.0.0/24"
        assert config.network_region == "us-central1"
        assert config.portal_network_cidrs == ("10.40.0.0/20", "10.44.0.0/16")

    def test_load_gdc_vmruntime_config_reads_sizing_contract(self, mocker):
        """VM Runtime config carries only sizing. Image URLs are fetched live at
        range-create time from Secret Manager via main.get_gdc_image_url."""
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GDC_VM_STORAGE_CLASS": "local-shared",
                "GDC_VM_IMAGE_GCS_SECRET_ID": "projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
                "GDC_KALI_VCPUS": "4",
                "GDC_KALI_MEMORY": "8Gi",
                "GDC_KALI_DISK_SIZE_GIB": "40",
            },
            clear=True,
        )

        config = load_gdc_vmruntime_config()

        assert config == GDCVMRuntimeConfig(
            storage_class_name="local-shared",
            image_gcs_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
            kali=GDCVMRuntimeProfile(vcpus=4, memory="8Gi", disk_size_gib=40),
            ubuntu=GDCVMRuntimeProfile(vcpus=1, memory="2Gi", disk_size_gib=20),
            windows=GDCVMRuntimeProfile(vcpus=2, memory="8Gi", disk_size_gib=64),
            dc=GDCVMRuntimeProfile(vcpus=2, memory="8Gi", disk_size_gib=64),
        )

    def test_gdc_vmruntime_config_get_profile_returns_sizing_by_role_and_os(self, mocker):
        """get_profile branches on role+os_type and returns sizing only.

        The image URL lookup is a separate call in the range-create path.
        Sizing is loaded at startup; URLs are looked up live.
        """
        mocker.patch.dict(
            os.environ,
            {"CLOUD_PROVIDER": "gcp"},
            clear=True,
        )

        config = load_gdc_vmruntime_config()

        assert config.get_profile(role="victim", os_type="ubuntu").disk_size_gib == 20
        assert config.get_profile(role="victim", os_type="kali").memory == "4Gi"
        assert config.get_profile(role="victim", os_type="windows").disk_size_gib == 64
        assert config.get_profile(role="dc", os_type="windows").vcpus == 2

    def test_load_gdc_palo_alto_vmseries_config_reads_required_contract(self, mocker):
        """VM-Series config carries bootstrap + sizing only. The image URL is
        fetched at NGFW provisioning time from Secret Manager via
        main.get_gdc_image_url('vmseries')."""
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GDC_VMSERIES_BOOTSTRAP_BUCKET": "shifter-gcp-dev-vmseries-bootstrap",
                "GDC_VMSERIES_STORAGE_CLASS": "local-shared",
                "GDC_VMSERIES_IMAGE_GCS_SECRET_ID": "projects/test/secrets/gcs-import",
                "GDC_VMSERIES_NAMESPACE_PREFIX": "ngfw",
                "GDC_VMSERIES_MGMT_NETWORK_NAME": "pod-network",
                "GDC_VMSERIES_MGMT_IP_CIDR": "10.200.0.20/24",
                "GDC_VMSERIES_DATA_NETWORK_NAME": "ngfw-data",
                "GDC_VMSERIES_DATA_IP_CIDR": "10.200.1.10/24",
                "GDC_VMSERIES_ROUTE_NEXT_HOP_IP": "10.200.1.1",
                "GDC_VMSERIES_VCPUS": "8",
                "GDC_VMSERIES_MEMORY": "16Gi",
                "GDC_VMSERIES_DISK_SIZE_GIB": "100",
                "GDC_VMSERIES_BOOTSTRAP_DISK_SIZE_GIB": "2",
                "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID": "projects/test/secrets/bootstrap-xml",
            },
            clear=True,
        )

        config = load_gdc_palo_alto_vmseries_config()

        assert config == GDCPaloAltoVMSeriesConfig(
            bootstrap_bucket="shifter-gcp-dev-vmseries-bootstrap",
            storage_class_name="local-shared",
            image_gcs_secret_id="projects/test/secrets/gcs-import",
            namespace_prefix="ngfw",
            management_network_name="pod-network",
            management_ip_cidr="10.200.0.20/24",
            data_network_name="ngfw-data",
            data_ip_cidr="10.200.1.10/24",
            route_next_hop_ip="10.200.1.1",
            vcpus=8,
            memory="16Gi",
            disk_size_gib=100,
            bootstrap_disk_size_gib=2,
            bootstrap_xml_template_secret_id="projects/test/secrets/bootstrap-xml",
        )

    def test_gdc_palo_alto_vmseries_config_requires_palo_alto_runtime_fields(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="GDC_VMSERIES_BOOTSTRAP_BUCKET"):
            load_gdc_palo_alto_vmseries_config()

    def test_load_gdc_scenario_pod_config_reads_explicit_image_contract(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GDC_SCENARIO_POD_IMAGE_PULL_POLICY": "Always",
                "GDC_SCENARIO_POD_KALI_IMAGE": (
                    "us-central1-docker.pkg.dev/test/shifter-gcp-dev-scenario-kali/scenario-kali:20260413"
                ),
                "GDC_SCENARIO_POD_UBUNTU_IMAGE": (
                    "us-central1-docker.pkg.dev/test/shifter-gcp-dev-scenario-ubuntu/scenario-ubuntu:20260413"
                ),
            },
            clear=True,
        )

        config = load_gdc_scenario_pod_config()

        assert config.image_pull_policy == "Always"
        assert (
            config.get_profile(os_type="kali").image
            == "us-central1-docker.pkg.dev/test/shifter-gcp-dev-scenario-kali/scenario-kali:20260413"
        )
        assert (
            config.get_profile(os_type="ubuntu").image
            == "us-central1-docker.pkg.dev/test/shifter-gcp-dev-scenario-ubuntu/scenario-ubuntu:20260413"
        )

    def test_load_gdc_scenario_pod_config_requires_explicit_images(self, mocker):
        mocker.patch.dict(
            os.environ,
            {"CLOUD_PROVIDER": "gcp"},
            clear=True,
        )

        config = load_gdc_scenario_pod_config()

        with pytest.raises(RuntimeError, match="Missing GDC scenario pod image"):
            config.get_profile(os_type="kali")


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
