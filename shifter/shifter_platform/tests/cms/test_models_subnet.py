"""Tests for cms.models.Subnet - Logical network segment model.

All tests use in-memory model construction and mocked ORM operations.
No database access required.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone
from pydantic import ValidationError

from shared.enums import ResourceStatus


# Helper to create valid instance spec dicts
def make_instance(name: str, role: str = "victim", os_type: str = "windows") -> dict:
    """Create a valid instance spec dict for testing."""
    return {"name": name, "role": role, "os_type": os_type}


def _make_subnet(**overrides):
    """Build a Subnet instance in-memory without touching the DB.

    Provides sensible defaults for all fields; any keyword argument
    overrides the corresponding attribute.  Uses __dict__ assignment
    to bypass Django descriptor validation for FK fields.
    """
    from cms.models import Subnet

    defaults = {
        "id": uuid4(),
        "name": "test_network",
        "status": ResourceStatus.PENDING.value,
        "created_at": timezone.now(),
        "deleted_at": None,
        "request_id": uuid4(),
        "data": {
            "instances": [
                make_instance("server1"),
                make_instance("server2"),
            ],
            "connected_to": ["other_network"],
        },
    }
    defaults.update(overrides)

    subnet = Subnet.__new__(Subnet)
    # Initialize Django model state so _state.adding / _state.db work
    subnet.__dict__["_state"] = Subnet()._state
    for key, value in defaults.items():
        subnet.__dict__[key] = value

    return subnet


# -----------------------------------------------------------------------------
# Subnet Model Basic Tests
# -----------------------------------------------------------------------------


class TestSubnetModel:
    """Tests for Subnet model structure and basic operations."""

    def test_create_subnet(self):
        """Can create a subnet with required fields."""
        subnet = _make_subnet(
            name="dc_network",
            data={
                "instances": [make_instance("domain_controller", "dc")],
                "connected_to": [],
            },
        )

        assert subnet.id is not None
        assert subnet.name == "dc_network"
        assert len(subnet.data["instances"]) == 1
        assert subnet.data["instances"][0]["name"] == "domain_controller"
        assert subnet.data["connected_to"] == []

    def test_str_returns_name_and_id(self):
        """__str__ returns name and UUID."""
        subnet = _make_subnet(name="test_network")
        result = str(subnet)

        assert "test_network" in result
        assert str(subnet.id) in result

    def test_default_status_is_pending(self):
        """Default status is 'pending'."""
        subnet = _make_subnet()

        assert subnet.status == ResourceStatus.PENDING.value

    def test_ordering_by_created_at_descending(self):
        """Subnets are ordered by created_at descending (Meta.ordering)."""
        from cms.models import Subnet

        assert Subnet._meta.ordering == ["-created_at"]


# -----------------------------------------------------------------------------
# EntityBase Inheritance Tests
# -----------------------------------------------------------------------------


class TestSubnetEntityBase:
    """Tests for Subnet's EntityBase inheritance."""

    def test_is_deleted_false_when_deleted_at_none(self):
        """is_deleted is False when deleted_at is None."""
        subnet = _make_subnet(deleted_at=None)

        assert subnet.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self):
        """is_deleted is True when deleted_at is set."""
        subnet = _make_subnet(deleted_at=timezone.now())

        assert subnet.is_deleted is True

    @patch("cms.models.Subnet.validate_data")
    def test_terminal_status_auto_sets_deleted_at(self, mock_validate):
        """Terminal status automatically sets deleted_at via EntityBase.save()."""
        subnet = _make_subnet(status=ResourceStatus.PENDING.value, deleted_at=None)

        # Transition to terminal status
        subnet.status = ResourceStatus.DESTROYED.value

        # Call save with the real EntityBase logic but mock the DB write
        with patch("django.db.models.Model.save"):
            subnet.save()

        assert subnet.deleted_at is not None
        assert subnet.is_deleted is True

    @patch("cms.models.Subnet.validate_data")
    def test_failed_status_auto_sets_deleted_at(self, mock_validate):
        """FAILED status automatically sets deleted_at."""
        subnet = _make_subnet(status=ResourceStatus.PENDING.value, deleted_at=None)

        subnet.status = ResourceStatus.FAILED.value

        with patch("django.db.models.Model.save"):
            subnet.save()

        assert subnet.deleted_at is not None


# -----------------------------------------------------------------------------
# Foreign Key Relationship Tests
# -----------------------------------------------------------------------------


class TestSubnetRelationships:
    """Tests for Subnet foreign key relationships."""

    def test_cascade_delete_configured(self):
        """Subnet.request FK is configured with CASCADE on_delete."""
        from django.db import models as dj_models

        from cms.models import Subnet

        field = Subnet._meta.get_field("request")
        assert isinstance(field, dj_models.ForeignKey)
        assert field.remote_field.on_delete is dj_models.CASCADE

    def test_request_subnets_related_name(self):
        """Subnet FK declares related_name='subnets'."""
        from cms.models import Subnet

        field = Subnet._meta.get_field("request")
        assert field.remote_field.related_name == "subnets"


# -----------------------------------------------------------------------------
# Data Field Tests
# -----------------------------------------------------------------------------


class TestSubnetData:
    """Tests for Subnet data JSONField."""

    def test_data_field_stores_json(self):
        """Data field stores and retrieves JSON data correctly (in-memory)."""
        subnet = _make_subnet(
            data={
                "instances": [
                    make_instance("server1"),
                    make_instance("server2"),
                    make_instance("server3"),
                ],
                "connected_to": ["network_a", "network_b"],
            },
        )

        assert len(subnet.data["instances"]) == 3
        assert subnet.data["instances"][0]["name"] == "server1"
        assert subnet.data["connected_to"] == ["network_a", "network_b"]

    def test_data_field_empty_connected_to(self):
        """Data field handles empty connected_to list (isolated subnet)."""
        subnet = _make_subnet(
            data={"instances": [make_instance("box1")], "connected_to": []},
        )

        assert subnet.data["connected_to"] == []


class TestSubnetValidation:
    """Tests for Subnet data validation."""

    def test_validation_rejects_empty_instances(self):
        """Validation rejects empty instances list."""
        subnet = _make_subnet(
            name="empty_instances",
            data={"instances": [], "connected_to": []},
        )

        with pytest.raises(ValidationError):
            subnet.validate_data()

    def test_validation_rejects_missing_instances(self):
        """Validation rejects missing instances field."""
        subnet = _make_subnet(
            name="no_instances",
            data={"connected_to": []},
        )

        with pytest.raises(ValidationError):
            subnet.validate_data()

    def test_instances_property_with_data(self):
        """instances property returns data['instances']."""
        subnet = _make_subnet()

        assert len(subnet.instances) == 2
        assert subnet.instances[0]["name"] == "server1"
        assert subnet.instances[1]["name"] == "server2"

    def test_instances_property_empty_data(self):
        """instances property returns empty list when data is empty."""
        subnet = _make_subnet(data={})

        assert subnet.instances == []

    def test_connected_to_property_with_data(self):
        """connected_to property returns data['connected_to']."""
        subnet = _make_subnet()

        assert subnet.connected_to == ["other_network"]

    def test_connected_to_property_empty_data(self):
        """connected_to property returns empty list when data is empty."""
        subnet = _make_subnet(data={})

        assert subnet.connected_to == []
