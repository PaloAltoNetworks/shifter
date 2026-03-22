"""Edge case tests for Shifter Engine config dataclasses."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import InstanceConfig, RangeConfig


class TestConfigBoundaryValues:
    """Boundary value tests for config dataclasses."""

    def test_range_config_empty_subnets(self):
        """RangeConfig accepts empty subnets list."""
        config = RangeConfig(
            range_id=42,
            user_id=1,
            request_uuid="test-uuid",
            environment="dev",
            subnets=[],
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            route_table_id="rtb-12345",
            instance_profile_name="profile",
            kali_ami_id="ami-kali",
            victim_ami_id="ami-ubuntu",
            windows_ami_id="ami-windows",
            agent_s3_bucket="bucket",
            availability_zone="us-east-2a",
        )
        assert config.subnets == []

    def test_instance_config_optional_fields_default_none(self):
        """InstanceConfig optional fields default to None."""
        config = InstanceConfig(
            uuid="inst-uuid-test",
            name="target-ubuntu",
            role="victim",
            os_type="ubuntu",
            instance_type="t3.micro",
        )
        assert config.agent_s3_key is None
        assert config.agent_presigned_url is None
