"""Tests for shared.schemas module - validation and type checking."""

from uuid import uuid4

import pytest


class TestRangeContextValidation:
    """Tests for RangeContext validation."""

    def test_rejects_empty_scenario_id(self):
        """RangeContext rejects empty scenario_id."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import InstanceContext, RangeContext

        with pytest.raises(ValueError, match="scenario_id cannot be empty"):
            RangeContext(
                request_id=uuid4(),
                scenario_id="",
                user_id=1,
                status=ResourceStatus.PENDING,
                instances=[],
            )

    def test_rejects_whitespace_scenario_id(self):
        """RangeContext rejects whitespace-only scenario_id."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        with pytest.raises(ValueError, match="scenario_id cannot be empty"):
            RangeContext(
                request_id=uuid4(),
                scenario_id="   ",
                user_id=1,
                status=ResourceStatus.PENDING,
                instances=[],
            )

    def test_rejects_zero_user_id(self):
        """RangeContext rejects user_id of zero."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            RangeContext(
                request_id=uuid4(),
                scenario_id="test-scenario",
                user_id=0,
                status=ResourceStatus.PENDING,
                instances=[],
            )

    def test_rejects_negative_user_id(self):
        """RangeContext rejects negative user_id."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            RangeContext(
                request_id=uuid4(),
                scenario_id="test-scenario",
                user_id=-1,
                status=ResourceStatus.PENDING,
                instances=[],
            )

    def test_rejects_zero_range_id_when_provided(self):
        """RangeContext rejects range_id of zero when provided."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        with pytest.raises(ValueError, match="range_id must be a positive integer"):
            RangeContext(
                request_id=uuid4(),
                range_id=0,
                scenario_id="test-scenario",
                user_id=1,
                status=ResourceStatus.PENDING,
                instances=[],
            )

    def test_accepts_none_range_id(self):
        """RangeContext accepts None for range_id."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        ctx = RangeContext(
            request_id=uuid4(),
            range_id=None,
            scenario_id="test-scenario",
            user_id=1,
            status=ResourceStatus.PENDING,
            instances=[],
        )
        assert ctx.range_id is None

    def test_computed_is_ready(self):
        """RangeContext.is_ready returns True when status is READY."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        ctx = RangeContext(
            request_id=uuid4(),
            scenario_id="test-scenario",
            user_id=1,
            status=ResourceStatus.READY,
            instances=[],
        )
        assert ctx.is_ready is True

    def test_computed_is_terminal(self):
        """RangeContext.is_terminal returns True for terminal statuses."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        for status in [ResourceStatus.DESTROYED, ResourceStatus.FAILED]:
            ctx = RangeContext(
                request_id=uuid4(),
                scenario_id="test-scenario",
                user_id=1,
                status=status,
                instances=[],
            )
            assert ctx.is_terminal is True

    def test_computed_is_active(self):
        """RangeContext.is_active returns True for non-terminal statuses."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.schemas import RangeContext

        for status in [ResourceStatus.PENDING, ResourceStatus.PROVISIONING, ResourceStatus.READY]:
            ctx = RangeContext(
                request_id=uuid4(),
                scenario_id="test-scenario",
                user_id=1,
                status=status,
                instances=[],
            )
            assert ctx.is_active is True


class TestRangeSpecValidation:
    """Tests for RangeSpec validation."""

    def test_rejects_empty_scenario_id(self):
        """RangeSpec rejects empty scenario_id."""
        from cyberscript.schemas import RangeSpec

        with pytest.raises(ValueError, match="scenario_id cannot be empty"):
            RangeSpec(
                scenario_id="",
                user_id=1,
                subnets=[],
            )

    def test_rejects_zero_user_id(self):
        """RangeSpec rejects user_id of zero."""
        from cyberscript.schemas import RangeSpec

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            RangeSpec(
                scenario_id="test-scenario",
                user_id=0,
                subnets=[],
            )


class TestInstanceSpecValidation:
    """Tests for InstanceSpec validation."""

    def test_creates_with_valid_role(self):
        """InstanceSpec creates with valid role."""
        from cyberscript.schemas import InstanceSpec

        spec = InstanceSpec(
            name="test-instance",
            role="attacker",
            os_type="kali",
        )
        assert spec.role == "attacker"

    def test_creates_with_valid_os_type(self):
        """InstanceSpec creates with valid os_type."""
        from cyberscript.schemas import InstanceSpec

        for os_type in ["kali", "ubuntu", "windows", "panos"]:
            spec = InstanceSpec(
                name=f"test-{os_type}",
                role="victim",
                os_type=os_type,
            )
            assert spec.os_type == os_type


class TestEventValidation:
    """Tests for event model validation."""

    def test_rejects_zero_range_id(self):
        """RangeStatusUpdatedEvent rejects range_id of zero."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.messages.events import RangeStatusUpdatedEvent

        with pytest.raises(ValueError, match="range_id must be a positive integer"):
            RangeStatusUpdatedEvent(
                range_id=0,
                user_id=1,
                new_status=ResourceStatus.PENDING,
            )

    def test_rejects_negative_range_id(self):
        """RangeStatusUpdatedEvent rejects negative range_id."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.messages.events import RangeStatusUpdatedEvent

        with pytest.raises(ValueError, match="range_id must be a positive integer"):
            RangeStatusUpdatedEvent(
                range_id=-1,
                user_id=1,
                new_status=ResourceStatus.PENDING,
            )

    def test_rejects_zero_user_id(self):
        """RangeStatusUpdatedEvent rejects user_id of zero."""
        from cyberscript.enums import ResourceStatus
        from cyberscript.messages.events import RangeStatusUpdatedEvent

        with pytest.raises(ValueError, match="user_id must be a positive integer"):
            RangeStatusUpdatedEvent(
                range_id=1,
                user_id=0,
                new_status=ResourceStatus.PENDING,
            )


class TestExceptionTypes:
    """Tests for exception types."""

    def test_cms_error_with_details(self):
        """CMSError stores message and details."""
        from cyberscript.exceptions import CMSError

        error = CMSError("Resource not found", details={"resource_id": 123})
        assert str(error) == "Resource not found (details: {'resource_id': 123})"
        assert error.message == "Resource not found"
        assert error.details == {"resource_id": 123}

    def test_cms_error_without_details(self):
        """CMSError works without details."""
        from cyberscript.exceptions import CMSError

        error = CMSError("Simple error")
        assert str(error) == "Simple error"

    def test_asset_error_with_type(self):
        """AssetError stores asset_type."""
        from cyberscript.exceptions import AssetError

        error = AssetError("Upload failed", asset_type="agent")
        assert "asset_type=agent" in str(error)

    def test_validation_error_with_field(self):
        """ValidationError stores field and value."""
        from cyberscript.exceptions import ValidationError

        error = ValidationError("Invalid value", field="user_id", value=-1)
        assert "field=user_id" in str(error)
        assert "value=-1" in str(error)

    def test_validation_error_truncates_long_values(self):
        """ValidationError truncates long values."""
        from cyberscript.exceptions import ValidationError

        long_value = "x" * 100
        error = ValidationError("Invalid value", field="data", value=long_value)
        assert "..." in str(error)

    def test_provisioning_error_with_resource_info(self):
        """ProvisioningError stores resource information."""
        from cyberscript.exceptions import ProvisioningError

        error = ProvisioningError(
            "Subnet exhausted",
            resource_type="range",
            resource_id="abc-123",
            details={"subnet_id": "subnet-xyz"},
        )
        assert "resource_type=range" in str(error)
        assert "resource_id=abc-123" in str(error)
