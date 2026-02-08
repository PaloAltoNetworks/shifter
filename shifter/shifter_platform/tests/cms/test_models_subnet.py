"""Tests for cms.models.Subnet - Logical network segment model."""

from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from pydantic import ValidationError

from shared.enums import RequestType, ResourceStatus

User = get_user_model()


# Helper to create valid instance spec dicts
def make_instance(name: str, role: str = "victim", os_type: str = "windows") -> dict:
    """Create a valid instance spec dict for testing."""
    return {"name": name, "role": role, "os_type": os_type}


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def request_obj(db, user):
    """Create a test Request."""
    from uuid import uuid4

    from cms.models import Request

    return Request.objects.create(
        request_id=uuid4(),
        request_type=RequestType.NGFW.value,
        user=user,
    )


@pytest.fixture
def subnet(db, request_obj):
    """Create a test Subnet."""
    from cms.models import Subnet

    return Subnet.objects.create(
        request=request_obj,
        name="test_network",
        data={
            "instances": [
                make_instance("server1"),
                make_instance("server2"),
            ],
            "connected_to": ["other_network"],
        },
    )


# -----------------------------------------------------------------------------
# Subnet Model Basic Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubnetModel:
    """Tests for Subnet model structure and basic operations."""

    def test_create_subnet(self, request_obj):
        """Can create a subnet with required fields."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="dc_network",
            data={
                "instances": [make_instance("domain_controller", "dc")],
                "connected_to": [],
            },
        )

        assert subnet.id is not None
        assert isinstance(subnet.id, UUID)
        assert subnet.request == request_obj
        assert subnet.name == "dc_network"
        assert len(subnet.data["instances"]) == 1
        assert subnet.data["instances"][0]["name"] == "domain_controller"
        assert subnet.data["connected_to"] == []

    def test_str_returns_name_and_id(self, subnet):
        """__str__ returns name and UUID."""
        result = str(subnet)

        assert "test_network" in result
        assert str(subnet.id) in result

    def test_default_status_is_pending(self, request_obj):
        """Default status is 'pending'."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="status_test",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )

        assert subnet.status == ResourceStatus.PENDING.value

    def test_ordering_by_created_at_descending(self, request_obj):
        """Subnets are ordered by created_at descending."""
        from cms.models import Subnet

        subnet1 = Subnet.objects.create(
            request=request_obj,
            name="first",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )
        subnet2 = Subnet.objects.create(
            request=request_obj,
            name="second",
            data={"instances": [make_instance("box2")], "connected_to": []},
        )

        subnets = list(Subnet.objects.filter(request=request_obj))

        assert subnets[0] == subnet2  # Newest first
        assert subnets[1] == subnet1


# -----------------------------------------------------------------------------
# EntityBase Inheritance Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubnetEntityBase:
    """Tests for Subnet's EntityBase inheritance."""

    def test_is_deleted_property(self, subnet, request_obj):
        """is_deleted reflects deleted_at state."""
        from cms.models import Subnet

        # False when deleted_at is None
        assert subnet.deleted_at is None
        assert subnet.is_deleted is False

        # True when deleted_at is set
        deleted_subnet = Subnet.objects.create(
            request=request_obj,
            name="deleted_test",
            data={"instances": [make_instance("box1")], "connected_to": []},
            deleted_at=timezone.now(),
        )
        assert deleted_subnet.is_deleted is True

    def test_terminal_status_auto_sets_deleted_at(self, request_obj):
        """Terminal status automatically sets deleted_at."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="terminal_test",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )
        assert subnet.deleted_at is None

        subnet.status = ResourceStatus.DESTROYED.value
        subnet.save()

        assert subnet.deleted_at is not None
        assert subnet.is_deleted is True

    def test_failed_status_auto_sets_deleted_at(self, request_obj):
        """FAILED status automatically sets deleted_at."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="failed_test",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )

        subnet.status = ResourceStatus.FAILED.value
        subnet.save()

        assert subnet.deleted_at is not None


# -----------------------------------------------------------------------------
# Foreign Key Relationship Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubnetRelationships:
    """Tests for Subnet foreign key relationships."""

    def test_subnet_deleted_when_request_deleted(self, request_obj):
        """Subnets cascade delete when Request is deleted."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="cascade_test",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )
        subnet_id = subnet.id

        request_obj.delete()

        assert not Subnet.objects.filter(id=subnet_id).exists()

    def test_request_subnets_related_name(self, request_obj):
        """Can access subnets via request.subnets."""
        from cms.models import Subnet

        Subnet.objects.create(
            request=request_obj,
            name="subnet1",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )
        Subnet.objects.create(
            request=request_obj,
            name="subnet2",
            data={"instances": [make_instance("box2")], "connected_to": []},
        )

        assert request_obj.subnets.count() == 2


# -----------------------------------------------------------------------------
# Data Field Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubnetData:
    """Tests for Subnet data JSONField."""

    def test_data_field_storage(self, request_obj):
        """Data field stores and retrieves JSON data correctly."""
        from cms.models import Subnet

        # Test with full data
        subnet = Subnet.objects.create(
            request=request_obj,
            name="data_test",
            data={
                "instances": [
                    make_instance("server1"),
                    make_instance("server2"),
                    make_instance("server3"),
                ],
                "connected_to": ["network_a", "network_b"],
            },
        )

        subnet.refresh_from_db()
        assert len(subnet.data["instances"]) == 3
        assert subnet.data["instances"][0]["name"] == "server1"
        assert subnet.data["connected_to"] == ["network_a", "network_b"]

        # Test empty connected_to (isolated subnet)
        isolated = Subnet.objects.create(
            request=request_obj,
            name="isolated",
            data={"instances": [make_instance("box1")], "connected_to": []},
        )
        isolated.refresh_from_db()
        assert isolated.data["connected_to"] == []


@pytest.mark.django_db
class TestSubnetValidation:
    """Tests for Subnet data validation."""

    def test_validation_rejects_empty_instances(self, request_obj):
        """Validation rejects empty instances list."""
        from cms.models import Subnet

        with pytest.raises(ValidationError):
            Subnet.objects.create(
                request=request_obj,
                name="empty_instances",
                data={"instances": [], "connected_to": []},
            )

    def test_validation_rejects_missing_instances(self, request_obj):
        """Validation rejects missing instances field."""
        from cms.models import Subnet

        with pytest.raises(ValidationError):
            Subnet.objects.create(
                request=request_obj,
                name="no_instances",
                data={"connected_to": []},
            )

    def test_instances_property(self, subnet, request_obj):
        """instances property returns data['instances'] or empty list."""
        from cms.models import Subnet

        # With data
        assert len(subnet.instances) == 2
        assert subnet.instances[0]["name"] == "server1"
        assert subnet.instances[1]["name"] == "server2"

        # Empty data returns empty list
        empty = Subnet(request=request_obj, name="test")
        empty.data = {}
        assert empty.instances == []

    def test_connected_to_property(self, subnet, request_obj):
        """connected_to property returns data['connected_to'] or empty list."""
        from cms.models import Subnet

        # With data
        assert subnet.connected_to == ["other_network"]

        # Empty data returns empty list
        empty = Subnet(request=request_obj, name="test")
        empty.data = {}
        assert empty.connected_to == []
