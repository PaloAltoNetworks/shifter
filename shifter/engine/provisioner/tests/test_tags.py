"""Tests for shared tagging utilities."""

import pytest

from components.tags import build_common_tags


class TestBuildCommonTags:
    """Tests for build_common_tags helper."""

    def test_minimal_required_params(self):
        """Test with only required parameters."""
        tags = build_common_tags(
            user_id=42,
            environment="dev",
            request_uuid="abc-123-def",
        )

        assert tags["shifter:user_id"] == "42"
        assert tags["shifter:environment"] == "dev"
        assert tags["shifter:request_uuid"] == "abc-123-def"
        assert tags["shifter:system"] == "shifter"
        assert tags["ManagedBy"] == "pulumi"
        # Should not have optional tags
        assert "shifter:range_id" not in tags
        assert "shifter:subnet_uuid" not in tags
        assert "shifter:instance_uuid" not in tags
        assert "shifter:component" not in tags

    def test_with_range_id(self):
        """Test with range_id included."""
        tags = build_common_tags(
            user_id=1,
            environment="prod",
            request_uuid="req-uuid",
            range_id=99,
        )

        assert tags["shifter:range_id"] == "99"

    def test_with_subnet_unit(self):
        """Test with subnet unit type."""
        tags = build_common_tags(
            user_id=1,
            environment="staging",
            request_uuid="req-uuid",
            unit_type="subnet",
            unit_uuid="subnet-uuid-456",
            unit_name="attack_network",
        )

        assert tags["shifter:subnet_uuid"] == "subnet-uuid-456"
        assert tags["shifter:subnet_name"] == "attack_network"
        assert "shifter:instance_uuid" not in tags

    def test_with_instance_unit(self):
        """Test with instance unit type."""
        tags = build_common_tags(
            user_id=1,
            environment="dev",
            request_uuid="req-uuid",
            unit_type="instance",
            unit_uuid="instance-uuid-789",
        )

        assert tags["shifter:instance_uuid"] == "instance-uuid-789"
        assert "shifter:subnet_uuid" not in tags
        # No name was provided
        assert "shifter:instance_name" not in tags

    def test_with_component(self):
        """Test with component identifier."""
        tags = build_common_tags(
            user_id=1,
            environment="dev",
            request_uuid="req-uuid",
            component="ngfw",
        )

        assert tags["shifter:component"] == "ngfw"


class TestBuildCommonTagsValidation:
    """Tests for input validation in build_common_tags."""

    def test_missing_user_id(self):
        """Test that missing user_id raises ValueError."""
        with pytest.raises(ValueError, match="user_id is required"):
            build_common_tags(
                user_id=None,  # type: ignore
                environment="dev",
                request_uuid="abc",
            )

    def test_invalid_user_id_type(self):
        """Test that non-integer user_id raises ValueError."""
        with pytest.raises(ValueError, match="must be a non-negative integer"):
            build_common_tags(
                user_id="42",  # type: ignore
                environment="dev",
                request_uuid="abc",
            )

    def test_negative_user_id(self):
        """Test that negative user_id raises ValueError."""
        with pytest.raises(ValueError, match="must be a non-negative integer"):
            build_common_tags(
                user_id=-1,
                environment="dev",
                request_uuid="abc",
            )

    def test_missing_environment(self):
        """Test that missing environment raises ValueError."""
        with pytest.raises(ValueError, match="environment is required"):
            build_common_tags(
                user_id=1,
                environment="",
                request_uuid="abc",
            )

    def test_missing_request_uuid(self):
        """Test that missing request_uuid raises ValueError."""
        with pytest.raises(ValueError, match="request_uuid is required"):
            build_common_tags(
                user_id=1,
                environment="dev",
                request_uuid="",
            )

    def test_unit_type_without_uuid(self):
        """Test that unit_type without unit_uuid raises ValueError."""
        with pytest.raises(ValueError, match="unit_uuid is required when unit_type is set"):
            build_common_tags(
                user_id=1,
                environment="dev",
                request_uuid="abc",
                unit_type="subnet",
            )

    def test_unit_uuid_without_type(self):
        """Test that unit_uuid without unit_type raises ValueError."""
        with pytest.raises(ValueError, match="unit_type is required when unit_uuid is set"):
            build_common_tags(
                user_id=1,
                environment="dev",
                request_uuid="abc",
                unit_uuid="some-uuid",
            )

    def test_invalid_unit_type(self):
        """Test that invalid unit_type raises ValueError."""
        with pytest.raises(ValueError, match="must be 'subnet' or 'instance'"):
            build_common_tags(
                user_id=1,
                environment="dev",
                request_uuid="abc",
                unit_type="invalid",  # type: ignore
                unit_uuid="some-uuid",
            )

    def test_negative_range_id(self):
        """Test that negative range_id raises ValueError."""
        with pytest.raises(ValueError, match="range_id must be a non-negative integer"):
            build_common_tags(
                user_id=1,
                environment="dev",
                request_uuid="abc",
                range_id=-5,
            )
