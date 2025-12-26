"""Edge case tests for Pulumi provisioner.

These tests exercise real code paths with mocked dependencies.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig, load_config


class TestLoadConfigEdgeCases:
    """Edge cases for load_config using real function calls."""

    @pytest.fixture
    def mock_pulumi_config(self, mocker):
        mock_config = MagicMock()
        mock_config.require.side_effect = lambda key: {
            "environment": "dev",
            "rangeVpcId": "vpc-test123",
            "rangeVpcCidr": "10.1.0.0/16",
            "rangeRouteTableId": "rtb-test123",
            "kaliSecurityGroupId": "sg-kali-test",
            "victimSecurityGroupId": "sg-victim-test",
            "kaliAmiId": "ami-kali-test",
            "victimAmiId": "ami-victim-test",
            "availabilityZone": "us-east-2a",
        }.get(key, f"mock-{key}")
        mock_config.require_int.side_effect = lambda key: {
            "rangeId": 0,
        }.get(key, 0)
        mock_config.get.side_effect = lambda key: {
            "agentS3Bucket": "test-agents-bucket",
            "windowsAmiId": "ami-windows-test",
            "dcAmiId": "ami-dc-test",
            "rangeInstanceProfileName": "test-profile",
            "portalVpcCidr": "10.0.0.0/16",
        }.get(key)
        mocker.patch("pulumi.Config", return_value=mock_config)
        return mock_config

    def test_load_config_range_id_zero(self, mock_pulumi_config, mocker, mock_boto3_clients):
        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 0,
                "user_id": 1,
                "subnet_index": 0,
                "agent_id": None,
                "instance_config": None,
                "agent_s3_key": None,
            },
        )

        result = load_config()

        assert result.range_id == 0
        assert result.subnet_index == 0
        assert len(result.instances) == 2  # defaults

    def test_load_config_large_range_id(self, mock_pulumi_config, mocker, mock_boto3_clients):
        mock_pulumi_config.require_int.side_effect = lambda key: {
            "rangeId": 999999,
        }.get(key, 0)

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 999999,
                "user_id": 1,
                "subnet_index": 5,
                "agent_id": None,
                "instance_config": None,
                "agent_s3_key": None,
            },
        )

        result = load_config()

        assert result.range_id == 999999

    def test_load_config_many_instances(self, mock_pulumi_config, mocker, mock_boto3_clients):
        instance_config = [
            {"role": "attacker", "os": "kali", "instance_type": "t3.small"}
        ] + [
            {"role": "victim", "os": "ubuntu", "instance_type": "t3.micro"}
            for _ in range(10)
        ]

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "subnet_index": 5,
                "agent_id": None,
                "instance_config": instance_config,
                "agent_s3_key": None,
            },
        )

        result = load_config()

        assert len(result.instances) == 11
        assert sum(1 for i in result.instances if i.role == "attacker") == 1
        assert sum(1 for i in result.instances if i.role == "victim") == 10

    def test_load_config_mixed_os_types(self, mock_pulumi_config, mocker, mock_boto3_clients):
        instance_config = [
            {"role": "victim", "os": "ubuntu", "instance_type": "t3.micro"},
            {"role": "victim", "os": "windows", "instance_type": "t3.medium"},
            {"role": "victim", "os": "amazon-linux", "instance_type": "t3.small"},
        ]

        mocker.patch(
            "config.get_range_from_db",
            return_value={
                "id": 42,
                "user_id": 1,
                "subnet_index": 5,
                "agent_id": None,
                "instance_config": instance_config,
                "agent_s3_key": None,
            },
        )

        result = load_config()

        os_types = {i.os_type for i in result.instances}
        assert os_types == {"ubuntu", "windows", "amazon-linux"}


class TestRangeConfigBoundaryValues:
    """RangeConfig should accept boundary values without error."""

    def test_empty_instances_list(self):
        config = RangeConfig(
            range_id=42,
            user_id=1,
            subnet_index=0,
            environment="dev",
            instances=[],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )
        assert config.instances == []

    def test_user_id_zero(self):
        config = RangeConfig(
            range_id=42,
            user_id=0,
            subnet_index=0,
            environment="dev",
            instances=[],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            kali_security_group_id="sg-kali",
            victim_security_group_id="sg-victim",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )
        assert config.user_id == 0


class TestInstanceConfigBoundaryValues:
    """InstanceConfig should accept empty optional fields."""

    def test_empty_agent_fields(self):
        config = InstanceConfig(
            role="victim",
            os_type="ubuntu",
            instance_type="t3.micro",
        )
        assert config.agent_id is None
        assert config.agent_s3_key is None
        assert config.agent_presigned_url is None
