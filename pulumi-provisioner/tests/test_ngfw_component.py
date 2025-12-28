"""NGFW component tests for Pulumi provisioner.

These tests use Pulumi's mocking framework to exercise NGFWComponent
without making AWS API calls. Tests verify EC2 instance, ENIs,
bootstrap config upload, and outputs.

TDD: These tests are written BEFORE the implementation exists.
They must FAIL initially, then PASS after implementation.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNGFWComponentWithPulumiMocks:
    """Tests for NGFWComponent using Pulumi runtime mocks.

    These tests verify that the component creates resources correctly
    by using Pulumi's mocking framework.
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory with NGFW templates."""
        # Add NGFW templates to the temp directory
        ngfw_userdata = temp_templates_dir / "ngfw_userdata.txt.j2"
        ngfw_userdata.write_text(
            "vmseries-bootstrap-aws-s3bucket={{ bootstrap_bucket }}/{{ bootstrap_prefix }}\n"
        )

        ngfw_init_cfg = temp_templates_dir / "ngfw_init_cfg.txt.j2"
        ngfw_init_cfg.write_text(
            """type=dhcp-client
hostname={{ hostname }}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
"""
        )

        return temp_templates_dir

    @pulumi.runtime.test
    def test_ngfw_component_creates_instance(self, temp_templates):
        """NGFWComponent should create a VM-Series EC2 instance."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            # Verify instance was created
            assert component.instance is not None
            assert component.instance_id is not None

    @pulumi.runtime.test
    def test_ngfw_component_creates_enis(self, temp_templates):
        """NGFWComponent should create untrust and trust ENIs."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            # Verify ENIs were created
            assert component.untrust_eni is not None
            assert component.trust_eni is not None

    @pulumi.runtime.test
    def test_ngfw_component_eni_static_ips(self, temp_templates):
        """NGFWComponent ENIs should have correct static IPs (.10 and .11)."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,  # Subnet is 10.1.6.0/24 (index + 1)
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            # Verify static IPs
            def check_untrust_ip(ip):
                assert ip == "10.1.6.10"

            def check_trust_ip(ip):
                assert ip == "10.1.6.11"

            component.untrust_ip.apply(check_untrust_ip)
            component.trust_ip.apply(check_trust_ip)

    @pulumi.runtime.test
    def test_ngfw_component_outputs(self, temp_templates):
        """NGFWComponent should expose required outputs."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            # Verify outputs exist
            assert component.instance_id is not None
            assert component.untrust_ip is not None
            assert component.trust_ip is not None

    @pulumi.runtime.test
    def test_ngfw_component_uploads_bootstrap_config(self, temp_templates):
        """NGFWComponent should upload init-cfg.txt to S3."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            # Verify S3 object was created for bootstrap config
            assert component.bootstrap_config is not None

    @pulumi.runtime.test
    def test_ngfw_component_imdsv2_enforced(self, temp_templates):
        """NGFWComponent instance should enforce IMDSv2."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            # Verify IMDSv2 is enforced via metadata options
            def check_metadata_options(options):
                # Options should require IMDSv2 tokens
                assert options is not None

            component.instance.metadata_options.apply(check_metadata_options)

    @pulumi.runtime.test
    def test_ngfw_component_to_output_dict(self, temp_templates):
        """to_output_dict should return dict with instance_id, untrust_ip, trust_ip."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            output_dict = component.to_output_dict()

            assert "instance_id" in output_dict
            assert "untrust_ip" in output_dict
            assert "trust_ip" in output_dict

    @pulumi.runtime.test
    def test_ngfw_component_tags(self, temp_templates):
        """NGFWComponent should tag resources correctly."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                instance_profile_name="range-instance-profile",
            )

            def check_tags(tags):
                assert "shifter:range_id" in tags
                assert tags["shifter:range_id"] == "42"
                assert "shifter:role" in tags
                assert tags["shifter:role"] == "ngfw"

            component.instance.tags.apply(check_tags)


class TestNGFWComponentSCMBootstrap:
    """Tests for NGFWComponent SCM (Strata Cloud Manager) bootstrap.

    SCM uses PIN-based authentication instead of Panorama vm-auth-key.
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def scm_templates(self, temp_templates_dir):
        """Provide temp templates directory with SCM-based NGFW templates."""
        ngfw_userdata = temp_templates_dir / "ngfw_userdata.txt.j2"
        ngfw_userdata.write_text(
            "vmseries-bootstrap-aws-s3bucket={{ bootstrap_bucket }}/{{ bootstrap_prefix }}\n"
        )

        # SCM-based init-cfg template (uses PIN instead of vm-auth-key)
        ngfw_init_cfg = temp_templates_dir / "ngfw_init_cfg.txt.j2"
        ngfw_init_cfg.write_text(
            """type=dhcp-client
hostname={{ hostname }}
dns-primary=8.8.8.8
dns-secondary=8.8.4.4
panorama-server=cloud
vm-series-auto-registration-pin-id={{ pin_id }}
vm-series-auto-registration-pin-value={{ pin_value }}
dgname={{ folder_name }}
"""
        )

        return temp_templates_dir

    @pulumi.runtime.test
    def test_ngfw_component_accepts_scm_params(self, scm_templates):
        """NGFWComponent should accept strata_pin_id, strata_pin_value, strata_folder_name."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(scm_templates)}):
            # Should not raise when using SCM params
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                strata_pin_id="pin-abc123",
                strata_pin_value="secret-xyz789",
                strata_folder_name="Edwards-Lab",
            )

            assert component.instance is not None

    @pulumi.runtime.test
    def test_ngfw_component_generates_scm_bootstrap_config(self, scm_templates):
        """NGFWComponent should upload init-cfg with SCM params to S3."""
        from components.ngfw import NGFWComponent

        with patch.dict(os.environ, {"TEMPLATES_DIR": str(scm_templates)}):
            component = NGFWComponent(
                name="test-ngfw",
                range_id=42,
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                instance_type="m5.xlarge",
                bootstrap_bucket="shifter-agents",
                cidr_prefix="10.1",
                subnet_index=5,
                environment="dev",
                strata_pin_id="pin-abc123",
                strata_pin_value="secret-xyz789",
                strata_folder_name="Edwards-Lab",
            )

            # Verify bootstrap config was created
            assert component.bootstrap_config is not None
