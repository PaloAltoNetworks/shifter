"""Configuration tests for Shifter Engine.

Tests for config utilities: presigned URLs, DB loading, dataclasses, and decryption.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    AcesContentDeliveryConfig,
    AWSPolarisAgentConfig,
    GCERangeCellConfig,
    GCERangeImageProfile,
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
    get_gcp_range_backend,
    get_range_availability_zone,
    get_range_from_db,
    is_gce_range_cell_backend,
    load_aces_content_delivery_config,
    load_aws_polaris_agent_config,
    load_gce_range_cell_config,
    load_gdc_network_access_config,
    load_gdc_palo_alto_vmseries_config,
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

    def test_gcp_range_backend_defaults_to_gce(self, mocker):
        mocker.patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True)

        assert get_gcp_range_backend() == "gce"
        assert is_gce_range_cell_backend() is True

    def test_gcp_range_backend_still_selects_gdc_explicitly(self, mocker):
        mocker.patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True)

        assert get_gcp_range_backend() == "gdc"
        assert is_gce_range_cell_backend() is False

    def test_gcp_range_backend_accepts_gce(self, mocker):
        mocker.patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True)

        assert get_gcp_range_backend() == "gce"
        assert is_gce_range_cell_backend() is True

    def test_gcp_range_backend_rejects_unknown_value(self, mocker):
        # The gce/gdc parse now lives in shared.range_instantiation_policy (#1348),
        # but get_gcp_range_backend() still raises RuntimeError for provisioner callers.
        mocker.patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "bogus"}, clear=True)

        with pytest.raises(RuntimeError, match="GCP_RANGE_BACKEND must be 'gdc' or 'gce'"):
            get_gcp_range_backend()

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
                "CLOUD_PROVIDER": "aws",
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
                "CLOUD_PROVIDER": "aws",
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
                "GCP_RANGE_BACKEND": "gdc",
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

    def test_load_range_network_config_uses_gce_pool_id_when_backend_is_gce(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "RANGE_NETWORK_CIDR": "10.50.0.0/16",
                "GCP_REGION": "us-central1",
            },
            clear=True,
        )

        config = load_range_network_config()

        assert config.network_id == "gcp-range-cells:test-project"
        assert config.network_cidr == "10.50.0.0/16"
        assert config.network_region == "us-central1"

    def test_load_gce_range_cell_config_reads_live_fire_contract(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "GCP_RANGE_LINUX_IMAGE": "projects/debian-cloud/global/images/family/debian-12",
                "GCP_RANGE_KALI_IMAGE": "projects/kali/global/images/kali",
                "GCP_RANGE_KALI_MACHINE_TYPE": "e2-standard-4",
                "GCP_RANGE_DC_IMAGE": "projects/windows-cloud/global/images/family/windows-2022",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "PORTAL_NETWORK_CIDRS": "10.40.0.0/20",
                "GCP_RANGE_EGRESS_ALLOW_CIDRS": "10.60.0.0/16",
            },
            clear=True,
        )

        config = load_gce_range_cell_config()

        assert config == GCERangeCellConfig(
            project_id="test-project",
            region="us-central1",
            zone="us-central1-b",
            network_mode="shared-vpc",
            network_id="projects/test-project/global/networks/range-net",
            service_account_email="range-host@test-project.iam.gserviceaccount.com",
            linux=GCERangeImageProfile(
                source_image="projects/debian-cloud/global/images/family/debian-12",
                machine_type="e2-standard-2",
                disk_size_gb=50,
            ),
            kali=GCERangeImageProfile(
                source_image="projects/kali/global/images/kali",
                machine_type="e2-standard-4",
                disk_size_gb=80,
            ),
            windows=GCERangeImageProfile(
                source_image="",
                machine_type="e2-standard-4",
                disk_size_gb=100,
            ),
            dc=GCERangeImageProfile(
                source_image="projects/windows-cloud/global/images/family/windows-2022",
                machine_type="e2-standard-4",
                disk_size_gb=100,
            ),
            portal_network_cidrs=("10.40.0.0/20",),
            egress_allow_cidrs=("10.60.0.0/16",),
        )

    def test_load_gce_range_cell_config_shared_vpc_requires_range_network_id(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "GCP_RANGE_KALI_IMAGE": "projects/shifter/global/images/polaris-vm",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="RANGE_NETWORK_ID"):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_supports_vpc_per_range_mode(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "GCP_RANGE_KALI_IMAGE": "projects/shifter/global/images/polaris-vm",
                "GCP_RANGE_CELL_NETWORK_MODE": "vpc-per-range",
            },
            clear=True,
        )

        config = load_gce_range_cell_config()

        assert config.network_mode == "vpc-per-range"
        assert config.network_id == ""

    def test_load_gce_range_cell_config_rejects_unknown_network_mode(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "GCP_RANGE_KALI_IMAGE": "projects/shifter/global/images/polaris-vm",
                "GCP_RANGE_CELL_NETWORK_MODE": "bogus",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="GCP_RANGE_CELL_NETWORK_MODE"):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_requires_host_service_account(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_LINUX_IMAGE": "projects/debian-cloud/global/images/family/debian-12",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL"):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_reads_host_mgmt_ssh_port(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "GCP_RANGE_KALI_IMAGE": "projects/shifter/global/images/polaris-vm",
                "GCP_RANGE_DC_IMAGE": "projects/shifter/global/images/polaris-dc",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_HOST_MGMT_SSH_PORT": "2229",
            },
            clear=True,
        )

        config = load_gce_range_cell_config()

        assert config.host_mgmt_ssh_port == 2229

    def test_gce_range_cell_config_host_mgmt_ssh_port_defaults_to_2222(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_KALI_IMAGE": "projects/shifter/global/images/polaris-vm",
            },
            clear=True,
        )

        assert load_gce_range_cell_config().host_mgmt_ssh_port == 2222

    def test_load_gce_range_cell_config_reads_private_google_access(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "GCP_RANGE_KALI_IMAGE": "projects/shifter/global/images/polaris-vm",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_PRIVATE_GOOGLE_ACCESS": "true",
            },
            clear=True,
        )

        config = load_gce_range_cell_config()

        assert config.private_google_access is True

    def test_gce_range_cell_config_get_profile_selects_guest_family(self):
        linux = GCERangeImageProfile(
            source_image="projects/debian-cloud/global/images/family/debian-12",
            machine_type="e2-small",
            disk_size_gb=20,
        )
        kali = GCERangeImageProfile(
            source_image="projects/kali/global/images/kali",
            machine_type="e2-standard-2",
            disk_size_gb=40,
        )
        windows = GCERangeImageProfile(
            source_image="projects/windows-cloud/global/images/family/windows-2022",
            machine_type="e2-standard-4",
            disk_size_gb=80,
        )
        dc = GCERangeImageProfile(
            source_image="projects/windows-cloud/global/images/family/windows-2022-dc",
            machine_type="e2-standard-8",
            disk_size_gb=100,
        )
        config = GCERangeCellConfig(
            project_id="test-project",
            region="us-central1",
            zone="us-central1-b",
            network_mode="vpc-per-range",
            linux=linux,
            kali=kali,
            windows=windows,
            dc=dc,
        )

        assert config.get_profile(role="dc", os_type="windows") == dc
        assert config.get_profile(role="attacker", os_type="kali") == kali
        assert config.get_profile(role="victim", os_type="windows") == windows
        assert config.get_profile(role="victim", os_type="ubuntu") == linux

        override = config.get_profile(role="victim", os_type="ubuntu", requested_type="n2-standard-4")
        assert override == GCERangeImageProfile(
            source_image=linux.source_image,
            machine_type="n2-standard-4",
            disk_size_gb=linux.disk_size_gb,
            disk_type=linux.disk_type,
        )

    def test_gce_range_cell_config_get_profile_honors_exact_ami_key_profile(self):
        default_kali = GCERangeImageProfile(
            source_image="projects/test/global/images/family/shifter-kali",
            machine_type="e2-standard-4",
            disk_size_gb=80,
        )
        polaris = GCERangeImageProfile(
            source_image="projects/test/global/images/family/shifter-polaris-vm",
            machine_type="e2-standard-8",
            disk_size_gb=210,
        )
        config = GCERangeCellConfig(
            project_id="test-project",
            region="us-central1",
            zone="us-central1-b",
            network_mode="vpc-per-range",
            kali=default_kali,
            image_key_profiles={"kali": {"polaris-vm": polaris}},
        )

        assert config.get_profile(role="attacker", os_type="kali") == default_kali
        assert config.get_profile(role="attacker", os_type="kali", ami_key="polaris-vm") == polaris
        with pytest.raises(RuntimeError, match="lowercase logical key"):
            config.get_profile(role="attacker", os_type="kali", ami_key="Polaris-VM")
        with pytest.raises(RuntimeError, match="no configured GCE image profile"):
            config.get_profile(role="attacker", os_type="kali", ami_key="techvault")
        with pytest.raises(RuntimeError, match="no configured GCE image profile"):
            config.get_profile(role="dc", os_type="windows", ami_key="polaris-vm")

    def test_load_gce_range_cell_config_parses_complete_image_key_profiles(self, mocker):
        mapping = {
            "kali": {
                "polaris-vm": {
                    "source_image": "projects/test/global/images/family/shifter-polaris-vm",
                    "machine_type": "e2-standard-8",
                    "disk_size_gb": 210,
                    "disk_type": "pd-balanced",
                }
            },
            "dc": {
                "polaris-dc": {
                    "source_image": "projects/test/global/images/family/shifter-polaris-dc",
                    "machine_type": "e2-standard-4",
                    "disk_size_gb": 100,
                    "disk_type": "pd-ssd",
                }
            },
        }
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_KALI_IMAGE": "projects/test/global/images/family/shifter-kali",
                "GCP_RANGE_DC_IMAGE": "projects/test/global/images/family/shifter-dc",
                "GCP_RANGE_IMAGE_KEY_PROFILES_JSON": json.dumps(mapping),
            },
            clear=True,
        )

        config = load_gce_range_cell_config()

        assert config.get_profile(role="attacker", os_type="kali", ami_key="polaris-vm").disk_size_gb == 210
        assert config.get_profile(role="dc", os_type="windows", ami_key="polaris-dc").disk_type == "pd-ssd"

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ("not-json", "valid JSON object"),
            ("[]", "valid JSON object"),
            ('{"kali":{"same":{},"same":{}}}', "duplicate JSON key"),
            ('{"attacker":{}}', "unknown profile class"),
            ('{"kali":{"Polaris":{}}}', "logical keys must be lowercase"),
            (
                '{"kali":{"polaris-vm":{"source_image":"family/polaris","machine_type":"e2-standard-8",'
                '"disk_size_gb":210,"disk_type":"pd-balanced","extra":true}}}',
                "unknown fields",
            ),
            (
                '{"kali":{"polaris-vm":{"source_image":"family/polaris","machine_type":"e2-standard-8",'
                '"disk_size_gb":20,"disk_type":"pd-balanced"}}}',
                "smaller than",
            ),
            (
                '{"kali":{"polaris-vm":{"source_image":"family/polaris","machine_type":"n2 standard",'
                '"disk_size_gb":210,"disk_type":"pd-balanced"}}}',
                "machine type",
            ),
            (
                '{"kali":{"polaris-vm":{"source_image":"family/polaris","machine_type":"e2-standard-8",'
                '"disk_size_gb":true,"disk_type":"pd-balanced"}}}',
                "positive integer",
            ),
            (
                '{"kali":{"polaris-vm":{"source_image":"family/polaris","machine_type":"e2-standard-8",'
                '"disk_size_gb":210,"disk_type":"pd-bogus"}}}',
                "supported Compute Engine disk type",
            ),
        ],
    )
    def test_load_gce_range_cell_config_rejects_invalid_image_key_profiles(self, mocker, raw, message):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_LINUX_IMAGE": "family/shifter-linux",
                "GCP_RANGE_IMAGE_KEY_PROFILES_JSON": raw,
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match=message):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_rejects_oversized_or_excessive_image_key_profiles(self, mocker):
        base_env = {
            "CLOUD_PROVIDER": "gcp",
            "GCP_RANGE_BACKEND": "gce",
            "GCP_PROJECT_ID": "test-project",
            "GCP_REGION": "us-central1",
            "RANGE_NETWORK_ZONE": "us-central1-b",
            "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
            "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
            "GCP_RANGE_LINUX_IMAGE": "family/shifter-linux",
        }
        mocker.patch.dict(
            os.environ,
            {
                **base_env,
                "GCP_RANGE_IMAGE_KEY_PROFILES_JSON": '{"linux":{"' + "a" * 32_769 + '":{}}}',
            },
            clear=True,
        )
        with pytest.raises(RuntimeError, match="32768-byte"):
            load_gce_range_cell_config()

        entry = {
            "source_image": "family/shifter-linux",
            "machine_type": "e2-standard-2",
            "disk_size_gb": 30,
            "disk_type": "pd-balanced",
        }
        profiles = {"linux": {f"image-{index}": entry for index in range(65)}}
        mocker.patch.dict(
            os.environ,
            {**base_env, "GCP_RANGE_IMAGE_KEY_PROFILES_JSON": json.dumps(profiles)},
            clear=True,
        )
        with pytest.raises(RuntimeError, match="64-entry"):
            load_gce_range_cell_config()

    def test_gce_range_cell_config_get_profile_falls_back_for_kali_without_image(self):
        linux = GCERangeImageProfile(source_image="projects/debian-cloud/global/images/family/debian-12")
        config = GCERangeCellConfig(
            project_id="test-project",
            region="us-central1",
            zone="us-central1-b",
            network_mode="vpc-per-range",
            linux=linux,
            kali=GCERangeImageProfile(),
        )

        assert config.get_profile(role="attacker", os_type="kali") == linux

    def test_gce_range_cell_config_get_profile_requires_selected_image(self):
        config = GCERangeCellConfig(
            project_id="test-project",
            region="us-central1",
            zone="us-central1-b",
            network_mode="vpc-per-range",
            linux=GCERangeImageProfile(),
            windows=GCERangeImageProfile(),
        )

        with pytest.raises(RuntimeError, match="Missing GCE range image"):
            config.get_profile(role="victim", os_type="windows")

    def test_load_gce_range_cell_config_rejects_malformed_image_reference(self, mocker):
        # A malformed image reference must fail at config load, not after the
        # Compute Engine create call rejects it (#1343 gap 7).
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_LINUX_IMAGE": "Not A Valid Image!!",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="GCP_RANGE_LINUX_IMAGE"):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_rejects_unknown_disk_type(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_LINUX_IMAGE": "projects/debian-cloud/global/images/family/debian-12",
                "GCP_RANGE_LINUX_DISK_TYPE": "pd-bogus",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="disk type"):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_rejects_disk_below_role_minimum(self, mocker):
        # Role-policy floor (NOT source-image validation): the documented
        # Windows/DC >=100 GB minimum is enforced before instance creation so an
        # obviously-undersized disk fails at config load, not at create time.
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_WINDOWS_IMAGE": "projects/shifter/global/images/family/shifter-windows",
                "GCP_RANGE_WINDOWS_DISK_SIZE_GB": "50",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="smaller than"):
            load_gce_range_cell_config()

    def test_load_gce_range_cell_config_accepts_valid_image_reference_forms(self, mocker):
        # Bare slug, family/<name>, and full projects/... paths are all valid.
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gce",
                "GCP_PROJECT_ID": "test-project",
                "GCP_REGION": "us-central1",
                "RANGE_NETWORK_ZONE": "us-central1-b",
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@test-project.iam.gserviceaccount.com",
                "RANGE_NETWORK_ID": "projects/test-project/global/networks/range-net",
                "GCP_RANGE_LINUX_IMAGE": "debian-12",
                "GCP_RANGE_KALI_IMAGE": "family/shifter-polaris-vm",
                "GCP_RANGE_DC_IMAGE": "projects/shifter/global/images/shifter-polaris-dc",
            },
            clear=True,
        )

        config = load_gce_range_cell_config()

        assert config.linux.source_image == "debian-12"
        assert config.kali.source_image == "family/shifter-polaris-vm"
        assert config.dc.source_image == "projects/shifter/global/images/shifter-polaris-dc"

    def test_load_gdc_vmruntime_config_reads_image_contract(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gdc",
                "GDC_VM_STORAGE_CLASS": "local-shared",
                "GDC_VM_IMAGE_GCS_SECRET_ID": "projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
                "GDC_KALI_IMAGE_URL": "gs://images/kali.qcow2",
                "GDC_KALI_VCPUS": "4",
                "GDC_KALI_MEMORY": "8Gi",
                "GDC_KALI_DISK_SIZE_GIB": "40",
                "GDC_UBUNTU_IMAGE_URL": "https://example.com/ubuntu.img",
                "GDC_WINDOWS_IMAGE_URL": "gs://images/windows.qcow2",
                "GDC_DC_IMAGE_URL": "docker://registry.example.com/dc-image:latest",
            },
            clear=True,
        )

        config = load_gdc_vmruntime_config()

        assert config == GDCVMRuntimeConfig(
            storage_class_name="local-shared",
            image_gcs_secret_id="projects/test/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
            kali=GDCVMRuntimeProfile(source_url="gs://images/kali.qcow2", vcpus=4, memory="8Gi", disk_size_gib=40),
            ubuntu=GDCVMRuntimeProfile(
                source_url="https://example.com/ubuntu.img",
                vcpus=1,
                memory="2Gi",
                disk_size_gib=20,
            ),
            windows=GDCVMRuntimeProfile(
                source_url="gs://images/windows.qcow2",
                vcpus=2,
                memory="8Gi",
                disk_size_gib=64,
            ),
            dc=GDCVMRuntimeProfile(
                source_url="docker://registry.example.com/dc-image:latest",
                vcpus=2,
                memory="8Gi",
                disk_size_gib=64,
            ),
        )

    def test_gdc_vmruntime_config_requires_matching_profile_when_selected(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gdc",
                "GDC_UBUNTU_IMAGE_URL": "https://example.com/ubuntu.img",
            },
            clear=True,
        )

        config = load_gdc_vmruntime_config()

        assert config.get_profile(role="victim", os_type="ubuntu").source_url == "https://example.com/ubuntu.img"
        with pytest.raises(RuntimeError, match="Missing GDC VM Runtime image URL"):
            config.get_profile(role="dc", os_type="windows")

    def test_load_gdc_palo_alto_vmseries_config_reads_required_contract(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "CLOUD_PROVIDER": "gcp",
                "GCP_RANGE_BACKEND": "gdc",
                "GDC_VMSERIES_IMAGE_URL": "gs://images/panos-vmseries.qcow2",
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
            image_url="gs://images/panos-vmseries.qcow2",
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
                "GCP_RANGE_BACKEND": "gdc",
                "GDC_VMSERIES_IMAGE_URL": "gs://images/panos-vmseries.qcow2",
            },
            clear=True,
        )

        with pytest.raises(RuntimeError, match="GDC_VMSERIES_BOOTSTRAP_BUCKET"):
            load_gdc_palo_alto_vmseries_config()


def _full_aws_polaris_agent_env() -> dict[str, str]:
    """Return a complete, valid AWS Polaris agent config env (#1377)."""
    return {
        "AWS_POLARIS_AGENT_REGION": "us-east-2",
        "AWS_POLARIS_AGENT_MAIN_MODEL_ID": "us.anthropic.claude-sonnet-4-6",
        "AWS_POLARIS_AGENT_SMALL_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN": (
            "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-sonnet-4-6-v1:0"
        ),
        "AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN": (
            "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-haiku-4-5-v1:0"
        ),
        "AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS": (
            "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-4-6-v1:0,"
            "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-6-v1:0"
        ),
        "AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS": (
            "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-v1:0"
        ),
        "AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS": "900",
        "AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS": "300",
        "AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN": "arn:aws:iam::123456789012:policy/ShifterPermissionsBoundary",
    }


class TestLoadAwsPolarisAgentConfig:
    """Tests for the AWS Polaris per-range Bedrock agent config seam (#1377).

    One validated seam for AWS region, approved main/small Bedrock model
    ids, their inference-profile/backing-model ARNs, and STS session
    lifecycle -- consumed by both Terraform agent-role rendering and
    PolarisRangeBootstrapPlan so model/ARN defaults live in exactly one
    place.
    """

    def test_returns_none_when_not_configured(self, mocker):
        """No AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN -> feature not enabled here."""
        mocker.patch.dict(os.environ, {}, clear=True)

        assert load_aws_polaris_agent_config() is None

    def test_reads_full_contract_from_env(self, mocker):
        mocker.patch.dict(os.environ, _full_aws_polaris_agent_env(), clear=True)

        config = load_aws_polaris_agent_config()

        assert config == AWSPolarisAgentConfig(
            region="us-east-2",
            main_model_id="us.anthropic.claude-sonnet-4-6",
            small_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
            main_inference_profile_arn=(
                "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-sonnet-4-6-v1:0"
            ),
            small_inference_profile_arn=(
                "arn:aws:bedrock:us-east-2:123456789012:inference-profile/us.anthropic.claude-haiku-4-5-v1:0"
            ),
            main_backing_model_arns=(
                "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-4-6-v1:0",
                "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-6-v1:0",
            ),
            small_backing_model_arns=("arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-haiku-4-5-v1:0",),
            sts_session_duration_seconds=900,
            refresh_window_seconds=300,
            permissions_boundary_arn="arn:aws:iam::123456789012:policy/ShifterPermissionsBoundary",
        )

    def test_defaults_model_ids_and_sts_timing_when_unset(self, mocker):
        """Absent optional env -> reuse the existing hardcoded defaults, not new ones.

        Same Bedrock model ids PolarisRangeBootstrapPlan previously carried as
        its own independent module constants (_AWS_DEFAULT_MODEL /
        _AWS_DEFAULT_SMALL_FAST_MODEL) -- now the one config seam owns them.
        """
        env = _full_aws_polaris_agent_env()
        del env["AWS_POLARIS_AGENT_MAIN_MODEL_ID"]
        del env["AWS_POLARIS_AGENT_SMALL_MODEL_ID"]
        del env["AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS"]
        del env["AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS"]
        mocker.patch.dict(os.environ, env, clear=True)

        config = load_aws_polaris_agent_config()

        assert config.main_model_id == "us.anthropic.claude-sonnet-4-6"
        assert config.small_model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        assert config.sts_session_duration_seconds == 900
        assert config.refresh_window_seconds == 300

    @pytest.mark.parametrize(
        "missing_key",
        [
            "AWS_POLARIS_AGENT_REGION",
            "AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN",
            "AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS",
            "AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS",
            "AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN",
        ],
    )
    def test_rejects_missing_required_field(self, mocker, missing_key):
        """The permissions boundary is part of the enabled-role contract (ADR-004-R21):
        an enabled agent role (main_inference_profile_arn set) with no boundary
        configured must fail closed here, not silently apply with
        permissions_boundary = null downstream (#1377 codex pre-push finding)."""
        env = _full_aws_polaris_agent_env()
        del env[missing_key]
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match=missing_key):
            load_aws_polaris_agent_config()

    @pytest.mark.parametrize(
        "model_key",
        ["AWS_POLARIS_AGENT_MAIN_MODEL_ID", "AWS_POLARIS_AGENT_SMALL_MODEL_ID"],
    )
    def test_rejects_blank_model_id(self, mocker, model_key):
        env = _full_aws_polaris_agent_env()
        env[model_key] = ""
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match=f"{model_key} must not be blank"):
            load_aws_polaris_agent_config()

    @pytest.mark.parametrize(
        "arn_key",
        [
            "AWS_POLARIS_AGENT_MAIN_INFERENCE_PROFILE_ARN",
            "AWS_POLARIS_AGENT_SMALL_INFERENCE_PROFILE_ARN",
            "AWS_POLARIS_AGENT_MAIN_BACKING_MODEL_ARNS",
            "AWS_POLARIS_AGENT_SMALL_BACKING_MODEL_ARNS",
            "AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN",
        ],
    )
    def test_rejects_malformed_arn(self, mocker, arn_key):
        env = _full_aws_polaris_agent_env()
        env[arn_key] = "not-an-arn"
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match=arn_key):
            load_aws_polaris_agent_config()

    def test_rejects_permissions_boundary_arn_that_is_not_a_policy_arn(self, mocker):
        """Boundary must be an IAM *policy* ARN specifically (arn:...:policy/...),
        not merely any IAM ARN -- a role/user/group ARN is not a valid permissions
        boundary target and the old generic IAM ARN pattern let it through."""
        env = _full_aws_polaris_agent_env()
        env["AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN"] = "arn:aws:iam::123456789012:role/SomeRole"
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match="AWS_POLARIS_AGENT_PERMISSIONS_BOUNDARY_ARN"):
            load_aws_polaris_agent_config()

    @pytest.mark.parametrize(
        "bad_region",
        [
            'us-east-2"; rm -rf /',
            "us-east-2$(whoami)",
            "us-east-2`whoami`",
            "US-EAST-2",
            "not-a-region",
            "us east 2",
            "us-east-2;whoami",
        ],
    )
    def test_rejects_shell_unsafe_or_malformed_region(self, mocker, bad_region):
        """region is substituted verbatim into a double-quoted shell variable
        assignment in the root-executed SSM range bootstrap scripts. A value
        carrying a quote, command substitution, backtick, or shell metacharacter
        must be rejected outright rather than merely checked for presence
        (#1377 codex pre-push finding: command injection into root-executed shell)."""
        env = _full_aws_polaris_agent_env()
        env["AWS_POLARIS_AGENT_REGION"] = bad_region
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match="AWS_POLARIS_AGENT_REGION"):
            load_aws_polaris_agent_config()

    def test_accepts_valid_region_shape(self, mocker):
        env = _full_aws_polaris_agent_env()
        env["AWS_POLARIS_AGENT_REGION"] = "us-west-2"
        mocker.patch.dict(os.environ, env, clear=True)

        config = load_aws_polaris_agent_config()

        assert config.region == "us-west-2"

    @pytest.mark.parametrize(
        "model_key",
        ["AWS_POLARIS_AGENT_MAIN_MODEL_ID", "AWS_POLARIS_AGENT_SMALL_MODEL_ID"],
    )
    @pytest.mark.parametrize(
        "bad_model_id",
        [
            'us.anthropic.claude-sonnet-4-6"; rm -rf /',
            "us.anthropic.claude-sonnet-4-6$(whoami)",
            "us.anthropic.claude-sonnet-4-6`whoami`",
            "us.anthropic claude-sonnet-4-6",
            "us.anthropic.claude-sonnet-4-6;whoami",
            "us.anthropic.claude-sonnet-4-6|whoami",
            "us.anthropic.claude-sonnet-4-6&whoami",
            "us.anthropic.claude-sonnet-4-6\nwhoami",
        ],
    )
    def test_rejects_shell_unsafe_model_id(self, mocker, model_key, bad_model_id):
        """main_model_id/small_model_id are substituted verbatim into
        double-quoted shell assignments in the root-executed SSM bootstrap
        scripts; only blankness was previously checked. A value carrying a
        quote, command substitution, backtick, or shell metacharacter must be
        rejected (#1377 codex pre-push finding: command injection)."""
        env = _full_aws_polaris_agent_env()
        env[model_key] = bad_model_id
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match=model_key):
            load_aws_polaris_agent_config()

    @pytest.mark.parametrize(
        "good_model_id",
        [
            "us.anthropic.claude-sonnet-4-6",
            "anthropic.claude-haiku-4-5-20251001-v1:0",
            "us.anthropic.claude-haiku-4-5-v1:0",
        ],
    )
    def test_accepts_valid_model_id_shapes(self, mocker, good_model_id):
        env = _full_aws_polaris_agent_env()
        env["AWS_POLARIS_AGENT_MAIN_MODEL_ID"] = good_model_id
        mocker.patch.dict(os.environ, env, clear=True)

        config = load_aws_polaris_agent_config()

        assert config.main_model_id == good_model_id

    def test_rejects_sts_session_duration_below_aws_minimum(self, mocker):
        env = _full_aws_polaris_agent_env()
        env["AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS"] = "300"
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match="AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS"):
            load_aws_polaris_agent_config()

    def test_rejects_refresh_window_not_less_than_session_duration(self, mocker):
        env = _full_aws_polaris_agent_env()
        env["AWS_POLARIS_AGENT_STS_SESSION_DURATION_SECONDS"] = "900"
        env["AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS"] = "900"
        mocker.patch.dict(os.environ, env, clear=True)

        with pytest.raises(RuntimeError, match="AWS_POLARIS_AGENT_REFRESH_WINDOW_SECONDS"):
            load_aws_polaris_agent_config()


class TestLoadAcesContentDeliveryConfig:
    """Tests for the #1564 post-boot content-delivery object-storage config."""

    def test_empty_bucket_when_unconfigured(self, mocker):
        """No bucket configured is legitimate -- most ranges have no source-backed
        content; the bucket is validated fail-closed only where delivery actually
        needs it, not eagerly at load time."""
        mocker.patch.dict(os.environ, {}, clear=True)

        config = load_aces_content_delivery_config()

        assert config == AcesContentDeliveryConfig(bucket="", max_bytes=268435456)

    def test_prefers_dedicated_bucket_env_var(self, mocker):
        mocker.patch.dict(
            os.environ,
            {"ACES_CONTENT_DELIVERY_BUCKET": "aces-delivery", "STORAGE_BUCKET_NAME": "platform-assets"},
            clear=True,
        )

        assert load_aces_content_delivery_config().bucket == "aces-delivery"

    def test_falls_back_to_shared_storage_bucket_name(self, mocker):
        """Same env var name the Django CMS side reads for the assets bucket, so a
        single shared value can configure both deployables."""
        mocker.patch.dict(os.environ, {"STORAGE_BUCKET_NAME": "platform-assets"}, clear=True)

        assert load_aces_content_delivery_config().bucket == "platform-assets"

    def test_reads_max_bytes_override(self, mocker):
        mocker.patch.dict(os.environ, {"ACES_CONTENT_DELIVERY_MAX_BYTES": "1024"}, clear=True)

        assert load_aces_content_delivery_config().max_bytes == 1024


class TestDecryptField:
    """Tests for decrypt_field function for encrypted database fields.

    Fail-closed contract (#1189): the function raises FieldDecryptError on
    every path that previously silently returned the input — missing
    encryption key, malformed base64, and Fernet token failures. Only the
    empty-input case (the explicit "no field present" sentinel) and the
    happy decrypt path return values.
    """

    # Test key for testing only
    # pragma: allowlist secret
    TEST_ENCRYPTION_KEY = "VbMOEgh9VmS5lr0EsIS2sD9X1iy-Qd12i4kVZHdgPVE="  # nosec B105

    def test_empty_value_returns_empty(self):
        """Empty string still returns empty (sentinel for absent field)."""
        assert decrypt_field("") == ""

    def test_no_key_with_non_empty_value_raises(self, mocker):
        """Missing FIELD_ENCRYPTION_KEY MUST fail closed, not pass through."""
        from config import FieldDecryptError

        mocker.patch.dict(os.environ, {}, clear=True)

        with pytest.raises(FieldDecryptError) as excinfo:
            decrypt_field("some-value")

        msg = str(excinfo.value)
        assert "FIELD_ENCRYPTION_KEY" in msg
        # Never leak the raw input value into the exception message.
        assert "some-value" not in msg

    def test_decrypts_valid_encrypted_value(self, mocker):
        """Valid Fernet-encrypted value round-trips."""
        import base64

        from cryptography.fernet import Fernet

        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": self.TEST_ENCRYPTION_KEY})

        fernet = Fernet(self.TEST_ENCRYPTION_KEY.encode())
        plaintext = "my-secret-pin-value"
        encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
        encrypted_value = base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")

        result = decrypt_field(encrypted_value)
        assert result == plaintext

    def test_malformed_base64_raises(self, mocker):
        """Input that isn't valid base64-url MUST fail closed."""
        from config import FieldDecryptError

        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": self.TEST_ENCRYPTION_KEY})

        with pytest.raises(FieldDecryptError) as excinfo:
            # Contains '!' which is not in the base64-url alphabet.
            decrypt_field("not-valid-base64!@#")

        msg = str(excinfo.value)
        assert "decrypt" in msg.lower()
        assert "not-valid-base64" not in msg

    def test_plaintext_looking_input_raises(self, mocker):
        """A valid-base64 string that is NOT a Fernet token MUST fail closed
        when the encryption key is present (drift signal)."""
        from config import FieldDecryptError

        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": self.TEST_ENCRYPTION_KEY})

        with pytest.raises(FieldDecryptError) as excinfo:
            decrypt_field("not-encrypted-just-plaintext")

        msg = str(excinfo.value)
        assert "not-encrypted-just-plaintext" not in msg

    def test_wrong_key_raises(self, mocker):
        """Valid Fernet token encrypted with a different key MUST fail closed."""
        import base64

        from cryptography.fernet import Fernet

        from config import FieldDecryptError

        # Encrypt with one key, attempt to decrypt with another. Both are
        # test-only Fernet keys (32 url-safe base64-encoded bytes).
        encryption_key_a = self.TEST_ENCRYPTION_KEY
        encryption_key_b = Fernet.generate_key().decode("ascii")
        assert encryption_key_a != encryption_key_b

        fernet = Fernet(encryption_key_a.encode())
        encrypted_bytes = fernet.encrypt(b"some-plaintext")
        encrypted_value = base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")

        mocker.patch.dict(os.environ, {"FIELD_ENCRYPTION_KEY": encryption_key_b})

        with pytest.raises(FieldDecryptError):
            decrypt_field(encrypted_value)


class TestResolveCloudProvider:
    """PLAT-2005: one validated CLOUD_PROVIDER resolution point.

    ``resolve_cloud_provider`` normalizes and validates against the
    ``installation`` registry (the single source of truth for supported
    backends) instead of the historical scattered
    ``os.environ.get("CLOUD_PROVIDER", "aws")`` reads. Tests pass an explicit
    ``env`` mapping so behavior does not depend on ambient process env or
    pytest's own invocation context, except where that context (running
    under pytest) is itself the thing under test.
    """

    def test_valid_aws_is_normalized(self):
        from config import resolve_cloud_provider

        assert resolve_cloud_provider({"CLOUD_PROVIDER": "AWS"}) == "aws"

    def test_valid_gcp_is_normalized(self):
        from config import resolve_cloud_provider

        assert resolve_cloud_provider({"CLOUD_PROVIDER": " gcp "}) == "gcp"

    def test_unknown_provider_fails_closed(self):
        from cloud.exceptions import CloudProviderNotImplementedError
        from config import resolve_cloud_provider

        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            resolve_cloud_provider({"CLOUD_PROVIDER": "azure"})

    def test_missing_allows_historical_aws_default_under_testing_flag(self):
        from config import resolve_cloud_provider

        assert resolve_cloud_provider({"TESTING": "1"}) == "aws"

    def test_missing_allows_historical_aws_default_under_environment_build(self):
        from config import resolve_cloud_provider

        assert resolve_cloud_provider({"ENVIRONMENT": "build"}) == "aws"

    def test_missing_allows_historical_aws_default_under_django_debug(self):
        from config import resolve_cloud_provider

        assert resolve_cloud_provider({"DJANGO_DEBUG": "true"}) == "aws"

    def test_missing_allows_historical_aws_default_under_pytest_invocation(self, monkeypatch):
        """No explicit dev-signal env key: falls back to the pytest-argv0 signal."""
        from config import resolve_cloud_provider

        monkeypatch.setattr("sys.argv", ["pytest"])

        assert resolve_cloud_provider({}) == "aws"

    def test_missing_environment_development_does_not_allow_default(self, monkeypatch):
        """ENVIRONMENT=development/dev is NOT a dev-default signal (deployed dev
        provisioners must receive CLOUD_PROVIDER explicitly)."""
        from cloud.exceptions import CloudProviderNotImplementedError
        from config import resolve_cloud_provider

        monkeypatch.setattr("sys.argv", ["/usr/bin/provisioner"])

        with pytest.raises(CloudProviderNotImplementedError):
            resolve_cloud_provider({"ENVIRONMENT": "development"})

    def test_missing_fails_closed_with_no_dev_signals(self, monkeypatch):
        from cloud.exceptions import CloudProviderNotImplementedError
        from config import resolve_cloud_provider

        monkeypatch.setattr("sys.argv", ["/usr/bin/provisioner"])

        with pytest.raises(CloudProviderNotImplementedError):
            resolve_cloud_provider({})

    def test_defaults_to_process_environ_when_no_env_mapping_given(self, mocker):
        from config import resolve_cloud_provider

        mocker.patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True)

        assert resolve_cloud_provider() == "gcp"
