"""Tests for cms.models.Subnet - Logical network segment model."""

from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from pydantic import ValidationError

from shared.enums import RequestType, ResourceStatus

User = get_user_model()


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
            "instances": ["server1", "server2"],
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
                "instances": ["domain_controller"],
                "connected_to": [],
            },
        )

        assert subnet.id is not None
        assert isinstance(subnet.id, UUID)
        assert subnet.request == request_obj
        assert subnet.name == "dc_network"
        assert subnet.data["instances"] == ["domain_controller"]
        assert subnet.data["connected_to"] == []

    def test_str_returns_name_and_id(self, subnet):
        """__str__ returns name and UUID."""
        result = str(subnet)

        assert "test_network" in result
        assert str(subnet.id) in result

    def test_uuid_primary_key_auto_generated(self, request_obj):
        """UUID primary key is auto-generated on creation."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="auto_uuid_test",
            data={"instances": ["box1"], "connected_to": []},
        )

        assert subnet.id is not None
        assert isinstance(subnet.id, UUID)

    def test_default_status_is_pending(self, request_obj):
        """Default status is 'pending'."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="status_test",
            data={"instances": ["box1"], "connected_to": []},
        )

        assert subnet.status == ResourceStatus.PENDING.value

    def test_ordering_by_created_at_descending(self, request_obj):
        """Subnets are ordered by created_at descending."""
        from cms.models import Subnet

        subnet1 = Subnet.objects.create(
            request=request_obj,
            name="first",
            data={"instances": ["box1"], "connected_to": []},
        )
        subnet2 = Subnet.objects.create(
            request=request_obj,
            name="second",
            data={"instances": ["box2"], "connected_to": []},
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

    def test_is_deleted_false_when_deleted_at_none(self, subnet):
        """is_deleted returns False when deleted_at is None."""
        assert subnet.deleted_at is None
        assert subnet.is_deleted is False

    def test_is_deleted_true_when_deleted_at_set(self, request_obj):
        """is_deleted returns True when deleted_at is set."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="deleted_test",
            data={"instances": ["box1"], "connected_to": []},
            deleted_at=timezone.now(),
        )

        assert subnet.is_deleted is True

    def test_terminal_status_auto_sets_deleted_at(self, request_obj):
        """Terminal status automatically sets deleted_at."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="terminal_test",
            data={"instances": ["box1"], "connected_to": []},
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
            data={"instances": ["box1"], "connected_to": []},
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
            data={"instances": ["box1"], "connected_to": []},
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
            data={"instances": ["box1"], "connected_to": []},
        )
        Subnet.objects.create(
            request=request_obj,
            name="subnet2",
            data={"instances": ["box2"], "connected_to": []},
        )

        assert request_obj.subnets.count() == 2


# -----------------------------------------------------------------------------
# Data Field Tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestSubnetData:
    """Tests for Subnet data JSONField."""

    def test_data_stores_instances_list(self, request_obj):
        """Data field stores instances list correctly."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="instances_test",
            data={"instances": ["server1", "server2", "server3"]},
        )

        subnet.refresh_from_db()
        assert subnet.data["instances"] == ["server1", "server2", "server3"]

    def test_data_stores_connected_to_list(self, request_obj):
        """Data field stores connected_to list correctly."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="connected_test",
            data={
                "instances": ["box1"],
                "connected_to": ["network_a", "network_b"],
            },
        )

        subnet.refresh_from_db()
        assert subnet.data["connected_to"] == ["network_a", "network_b"]

    def test_data_handles_empty_connected_to(self, request_obj):
        """Data field handles empty connected_to (isolated subnet)."""
        from cms.models import Subnet

        subnet = Subnet.objects.create(
            request=request_obj,
            name="isolated",
            data={"instances": ["box1"], "connected_to": []},
        )

        subnet.refresh_from_db()
        assert subnet.data["connected_to"] == []


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

    def test_instances_property(self, subnet):
        """instances property returns data['instances']."""
        assert subnet.instances == ["server1", "server2"]

    def test_connected_to_property(self, subnet):
        """connected_to property returns data['connected_to']."""
        assert subnet.connected_to == ["other_network"]

    def test_instances_property_empty_data(self, request_obj):
        """instances property returns empty list if data missing."""
        from cms.models import Subnet

        # Create without validation by using _state trick
        subnet = Subnet(request=request_obj, name="test")
        subnet.data = {}
        assert subnet.instances == []

    def test_connected_to_property_empty_data(self, request_obj):
        """connected_to property returns empty list if data missing."""
        from cms.models import Subnet

        subnet = Subnet(request=request_obj, name="test")
        subnet.data = {}
        assert subnet.connected_to == []
