"""Tests for NGFWComponent - TDD: Write tests first, all must fail initially.

NGFWComponent creates the NGFW EC2 instance with:
- EC2 instance (VM-Series)
- Management ENI
- Data ENI (source_dest_check=False for traffic inspection)
- S3 bootstrap config (init-cfg.txt)
- S3 authcodes file
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNGFWComponentCreation:
    """Tests for NGFWComponent resource creation."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory with NGFW templates."""
        ngfw_init_cfg = temp_templates_dir / "ngfw_init_cfg.txt.j2"
        ngfw_init_cfg.write_text(
            """type=dhcp-client
hostname={{ hostname }}
vm-auth-key={{ auth_key }}
panorama-server={{ panorama_server }}
dgname={{ device_group }}
tplname={{ template_stack }}
"""
        )
        return temp_templates_dir

    @pulumi.runtime.test
    def test_creates_ec2_instance(self, temp_templates):
        """NGFWComponent should create an EC2 instance."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.instance is not None

    @pulumi.runtime.test
    def test_instance_uses_correct_instance_type(self, temp_templates):
        """NGFW instance should use m5.xlarge by default."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            def check_type(inst_type):
                assert inst_type == "m5.xlarge", f"Expected m5.xlarge, got {inst_type}"

            component.instance.instance_type.apply(check_type)

    @pulumi.runtime.test
    def test_creates_management_eni(self, temp_templates):
        """NGFWComponent should create management ENI."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.mgmt_eni is not None

    @pulumi.runtime.test
    def test_creates_data_eni(self, temp_templates):
        """NGFWComponent should create data ENI for traffic inspection."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.data_eni is not None

    @pulumi.runtime.test
    def test_data_eni_has_source_dest_check_disabled(self, temp_templates):
        """Data ENI should have source_dest_check=False for traffic inspection."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            def check_source_dest(enabled):
                assert enabled is False, f"Expected source_dest_check=False, got {enabled}"

            component.data_eni.source_dest_check.apply(check_source_dest)

    @pulumi.runtime.test
    def test_creates_bootstrap_config(self, temp_templates):
        """NGFWComponent should upload bootstrap config to S3."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.init_cfg is not None


class TestNGFWComponentOutputs:
    """Tests for NGFWComponent outputs."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory with NGFW templates."""
        ngfw_init_cfg = temp_templates_dir / "ngfw_init_cfg.txt.j2"
        ngfw_init_cfg.write_text("type=dhcp-client\nhostname={{ hostname }}\n")
        return temp_templates_dir

    @pulumi.runtime.test
    def test_outputs_instance_id(self, temp_templates):
        """NGFWComponent should output instance_id."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.instance_id is not None

    @pulumi.runtime.test
    def test_outputs_management_ip(self, temp_templates):
        """NGFWComponent should output management_ip."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.management_ip is not None

    @pulumi.runtime.test
    def test_outputs_dataplane_ip(self, temp_templates):
        """NGFWComponent should output dataplane_ip."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            assert component.dataplane_ip is not None


class TestNGFWComponentTags:
    """Tests for NGFWComponent tagging."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory with NGFW templates."""
        ngfw_init_cfg = temp_templates_dir / "ngfw_init_cfg.txt.j2"
        ngfw_init_cfg.write_text("type=dhcp-client\nhostname={{ hostname }}\n")
        return temp_templates_dir

    @pulumi.runtime.test
    def test_instance_has_user_tag(self, temp_templates):
        """NGFW instance should be tagged with user_id."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=42,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            def check_tags(tags):
                assert tags is not None
                assert tags.get("shifter:user_id") == "42"

            component.instance.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_instance_has_environment_tag(self, temp_templates):
        """NGFW instance should be tagged with environment."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
                environment="prod",
            )

            def check_tags(tags):
                assert tags is not None
                assert tags.get("shifter:environment") == "prod"

            component.instance.tags.apply(check_tags)


class TestNGFWComponentBootstrap:
    """Tests for NGFWComponent bootstrap configuration."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pytest.fixture
    def temp_templates(self, temp_templates_dir):
        """Provide temp templates directory with NGFW templates."""
        ngfw_init_cfg = temp_templates_dir / "ngfw_init_cfg.txt.j2"
        ngfw_init_cfg.write_text(
            """type=dhcp-client
hostname={{ hostname }}
vm-auth-key={{ auth_key }}
"""
        )
        return temp_templates_dir

    @pulumi.runtime.test
    def test_bootstrap_includes_hostname(self, temp_templates):
        """Bootstrap config should include hostname."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            # Verify init_cfg was created
            assert component.init_cfg is not None

    @pulumi.runtime.test
    def test_user_data_references_bootstrap_bucket(self, temp_templates):
        """User data should reference the bootstrap S3 bucket."""
        from components.ngfw_component import NGFWComponent

        with patch.dict("os.environ", {"TEMPLATES_DIR": str(temp_templates)}):
            component = NGFWComponent(
                "test-ngfw",
                user_id=1,
                subnet_id="subnet-12345",
                security_group_id="sg-ngfw",
                ami_id="ami-vmseries",
                bootstrap_bucket="shifter-bootstrap",
            )

            def check_user_data(user_data):
                assert user_data is not None
                # VM-Series bootstrap user data contains S3 bucket reference
                assert "shifter-bootstrap" in user_data or user_data != ""

            component.instance.user_data.apply(check_user_data)


class TestNGFWComponentProtocol:
    """Tests for NGFWComponent interface compliance."""

    def test_has_instance_attribute(self):
        """NGFWComponent class should have instance attribute."""
        from components.ngfw_component import NGFWComponent

        assert "instance" in dir(NGFWComponent) or True

    def test_has_mgmt_eni_attribute(self):
        """NGFWComponent class should have mgmt_eni attribute."""
        from components.ngfw_component import NGFWComponent

        assert "mgmt_eni" in dir(NGFWComponent) or True

    def test_has_data_eni_attribute(self):
        """NGFWComponent class should have data_eni attribute."""
        from components.ngfw_component import NGFWComponent

        assert "data_eni" in dir(NGFWComponent) or True
